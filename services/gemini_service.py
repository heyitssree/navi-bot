# services/gemini_service.py - Gemini API wrapper: dual-key fallback, error classes, circuit breaker

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Literal

import sqlite3
from google import genai

logger = logging.getLogger("navi.gemini")

ErrorKind = Literal["rate_limited", "server", "config"]

DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.8-flash"

_DEFAULT_RETRY_AFTER = 20.0            # seconds, when a 429 carries no retry delay
_BREAKER_FAILURE_THRESHOLD = 3         # consecutive server failures
_BREAKER_OPEN_SECONDS = 300.0          # 5 minutes, then one half-open probe
_CONFIG_LOG_INTERVAL = 600.0           # log config errors at most every 10 minutes
_CONFIG_ALERT_INTERVAL = 3600.0        # DM the owner at most once an hour


class ClassifiedError(Exception):
    def __init__(self, kind: ErrorKind, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


def _retry_delay(exc: Exception) -> float | None:
    """Pull the server-suggested retry delay out of a Gemini 429, if present."""
    details = getattr(exc, "details", None)
    try:
        for item in (details or {}).get("error", {}).get("details", []):
            delay = item.get("retryDelay")
            if delay:
                return float(str(delay).rstrip("s"))
    except (AttributeError, ValueError, TypeError):
        pass
    m = re.search(r"retry in ([\d.]+)\s*s", str(exc), re.IGNORECASE)
    return float(m.group(1)) if m else None


def classify_error(exc: Exception) -> ClassifiedError:
    """Map a provider exception onto rate_limited / config / server."""
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return ClassifiedError("rate_limited", str(exc), _retry_delay(exc) or _DEFAULT_RETRY_AFTER)
    if code in (400, 401, 403, 404) or status in (
        "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND",
    ):
        return ClassifiedError("config", str(exc))
    # 5xx, timeouts, connection resets, anything unexpected
    return ClassifiedError("server", f"{type(exc).__name__}: {exc}")


class CircuitBreaker:
    """closed -> (3 consecutive failures | immediate trip) -> open -> (timeout) -> half-open probe."""

    def __init__(
        self,
        threshold: int = _BREAKER_FAILURE_THRESHOLD,
        open_seconds: float = _BREAKER_OPEN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self.failures = 0
        self._open_until: float | None = None
        self._probing = False

    @property
    def is_open(self) -> bool:
        """True while callers must not reach the provider (pure query, no state change)."""
        with self._lock:
            if self._probing:
                return True
            return self._open_until is not None and self._clock() < self._open_until

    @property
    def seconds_left(self) -> float:
        with self._lock:
            if self._open_until is None:
                return 0.0
            return max(0.0, self._open_until - self._clock())

    def allow(self) -> bool:
        """Ask permission to call the provider. After the open period exactly one probe is let through."""
        with self._lock:
            if self._open_until is None:
                return True
            if self._clock() < self._open_until or self._probing:
                return False
            self._probing = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self._open_until = None
            self._probing = False

    def record_failure(self) -> None:
        with self._lock:
            if self._probing:
                self._probing = False
                self._open_until = self._clock() + self.open_seconds
                return
            self.failures += 1
            if self.failures >= self.threshold:
                self._open_until = self._clock() + self.open_seconds

    def trip(self) -> None:
        """Open immediately (configuration errors)."""
        with self._lock:
            self._probing = False
            self._open_until = self._clock() + self.open_seconds

    def release_probe(self) -> None:
        """A probe ended without a verdict (e.g. rate limited): allow another probe next time."""
        with self._lock:
            if self._probing:
                self._probing = False
                self._open_until = self._clock()


class GeminiService:
    """Wraps Gemini API calls with:
    - Free-key-first, paid-key-fallback dual key strategy
    - Error classes: rate_limited (per-key cooldown, never trips the breaker),
      config (alert owner, open breaker at once), server (3 in a row open it for 5 minutes)
    """

    def __init__(
        self,
        free_api_key: str | None,
        paid_api_key: str | None,
        db_conn: sqlite3.Connection,
        model: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not free_api_key and not paid_api_key:
            raise ValueError(
                "Navi needs at least one Gemini API key. "
                "Set GEMINI_API_KEY_FREE or GEMINI_API_KEY_PAID in .env"
            )

        self._free_client: genai.Client | None = (
            genai.Client(api_key=free_api_key) if free_api_key else None
        )
        self._paid_client: genai.Client | None = (
            genai.Client(api_key=paid_api_key) if paid_api_key else None
        )
        self._db_conn = db_conn
        self._clock = clock
        self.model: str = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL

        self.breaker = CircuitBreaker(clock=clock)
        self._key_cooldown: dict[str, float] = {}
        self._last_config_log = -_CONFIG_LOG_INTERVAL
        self._last_config_alert = -_CONFIG_ALERT_INTERVAL
        # Set by bot.py; called from a worker thread with a short message for the owner.
        self.on_config_error: Callable[[str], None] | None = None

        self.active_key: str = "none"  # "free" | "paid" | "none"
        self.free_only: bool = False

        # Usage counters (lifetime, since last bot restart)
        self.free_calls: int = 0
        self.paid_calls: int = 0
        self.failed_calls: int = 0

        keys_available = []
        if free_api_key:
            keys_available.append("free")
        if paid_api_key:
            keys_available.append("paid")
        logger.info("GeminiService initialised. Available keys: %s, model: %s", keys_available, self.model)

    # ------------------------------------------------------------------
    # Backwards-compatible views of breaker state
    # ------------------------------------------------------------------

    @property
    def failure_count(self) -> int:
        return self.breaker.failures

    @property
    def is_circuit_open(self) -> bool:
        """True when the breaker is open and we're serving cache/fallbacks only."""
        return self.breaker.is_open

    @property
    def open_until(self) -> datetime | None:
        left = self.breaker.seconds_left
        return datetime.now() + timedelta(seconds=left) if left > 0 else None

    # ------------------------------------------------------------------
    # Startup check
    # ------------------------------------------------------------------

    def verify_model(self) -> str:
        """Check the configured model is callable with our key; else try FALLBACK_MODEL. Logs the active model."""
        client = self._free_client or self._paid_client
        try:
            available = {m.name.removeprefix("models/") for m in client.models.list()}
        except Exception as exc:
            err = classify_error(exc)
            if err.kind == "config":
                self._handle_config_error("startup model check", err)
            else:
                logger.warning("Could not list Gemini models (%s); keeping model %s.", err, self.model)
            return self.model

        if self.model not in available:
            logger.error("Configured model %r is not available to this key.", self.model)
            if FALLBACK_MODEL in available and FALLBACK_MODEL != self.model:
                logger.error("Falling back to %s.", FALLBACK_MODEL)
                self.model = FALLBACK_MODEL
            else:
                logger.error("Fallback model %s is not available either; calls will likely fail.", FALLBACK_MODEL)
        logger.info("Active Gemini model: %s", self.model)
        return self.model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(self, prompt: str, system_prompt: str) -> str | None:
        """Attempt a Gemini API call using free key first, then paid key.

        Returns the response text on success, or None when no key could answer
        (caller then falls back to cache / its own fallback text).
        """
        if not self.breaker.allow():
            logger.warning("Circuit OPEN - fallback mode for ~%d more seconds.", int(self.breaker.seconds_left))
            return None

        keys = []
        if self._free_client:
            keys.append(("free", self._free_client))
        if self._paid_client and not self.free_only:
            keys.append(("paid", self._paid_client))

        server_failure = False
        tried = False
        for name, client in keys:
            if self._clock() < self._key_cooldown.get(name, 0.0):
                continue
            tried = True
            try:
                text = self._try_key(client, prompt, system_prompt, name)
            except Exception as exc:
                err = classify_error(exc)
                if err.kind == "rate_limited":
                    self._key_cooldown[name] = self._clock() + (err.retry_after or _DEFAULT_RETRY_AFTER)
                    logger.warning("Gemini %s key rate limited; cooling down %.0fs.", name, err.retry_after or 0)
                    continue
                if err.kind == "config":
                    self._handle_config_error(f"{name} key", err)
                    self.failed_calls += 1
                    self.active_key = "none"
                    return None
                logger.warning("Gemini %s key server error: %s", name, err)
                server_failure = True
                continue
            if text:
                self.breaker.record_success()
                self.active_key = name
                if name == "free":
                    self.free_calls += 1
                else:
                    self.paid_calls += 1
                return text
            logger.warning("Gemini %s key returned an empty response.", name)

        self.failed_calls += 1
        self.active_key = "none"
        if server_failure:
            self.breaker.record_failure()
            logger.error("Gemini server failure. Breaker failures: %d/%d", self.breaker.failures, self.breaker.threshold)
        else:
            if not tried:
                logger.warning("All Gemini keys are cooling down after rate limits.")
            self.breaker.release_probe()
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _handle_config_error(self, where: str, err: ClassifiedError) -> None:
        now = self._clock()
        if now - self._last_config_log >= _CONFIG_LOG_INTERVAL:
            self._last_config_log = now
            logger.error("Gemini configuration error (%s, model=%s): %s", where, self.model, err)
        if self.on_config_error and now - self._last_config_alert >= _CONFIG_ALERT_INTERVAL:
            self._last_config_alert = now
            try:
                self.on_config_error(
                    f"Gemini config error ({where}, model `{self.model}`): {str(err)[:300]}. "
                    f"Check the API key / LLM_MODEL. Falling back to cache until fixed."
                )
            except Exception:
                logger.exception("Owner alert callback failed.")
        self.breaker.trip()

    def _try_key(self, client: genai.Client, prompt: str, system_prompt: str, key_name: str) -> str | None:
        """One Gemini call. Raises on provider errors; returns response text (possibly empty)."""
        logger.debug("Trying %s key for prompt: %.80s...", key_name, prompt)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "system_instruction": system_prompt,
                "temperature": 0.8,
            },
        )
        text = response.text
        if text:
            logger.info("Gemini %s key responded OK (%.60s...).", key_name, text)
        return text

    def status_dict(self) -> dict:
        """Return a status snapshot for the /health command."""
        total = self.free_calls + self.paid_calls + self.failed_calls
        free_pct = round(self.free_calls / total * 100) if total else 0
        paid_pct = round(self.paid_calls / total * 100) if total else 0
        left = self.breaker.seconds_left
        return {
            "model": self.model,
            "circuit_open": self.is_circuit_open,
            "failure_count": self.failure_count,
            "open_until": self.open_until.isoformat() if self.open_until else "N/A",
            "active_key": self.active_key,
            "free_key_available": self._free_client is not None,
            "paid_key_available": self._paid_client is not None,
            "cooldowns": {k: max(0, int(v - self._clock())) for k, v in self._key_cooldown.items() if v > self._clock()},
            "circuit_seconds_left": int(left),
            # Usage counters
            "free_calls": self.free_calls,
            "paid_calls": self.paid_calls,
            "failed_calls": self.failed_calls,
            "total_calls": total,
            "free_pct": free_pct,
            "paid_pct": paid_pct,
        }
