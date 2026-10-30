# navi/llm/router.py - budget, priority, cooldowns, breaker, safety and fallback in front of any LLMProvider
#
# Request flow (replaces services/api_manager.py + the breaker in services/gemini_service.py):
#   1. router disabled (killswitch / provider off)      -> caller's fallback
#   2. shared RPM budget (fixed 60 s window); purposes with PRIORITY >= 2 yield when little budget is left
#   3. breaker open                                     -> fallback (cacheable purposes may use the template pool)
#   4. per key: skip while cooling down; call provider; classify LLMError
#        rate_limited -> cool that key down (retry_after or 20 s); NOT a breaker failure
#        config       -> log ERROR (throttled), DM owner (max 1/h), open breaker at once
#        server       -> 3 consecutive open the breaker for 5 minutes, then one half-open probe
#   5. safety.check_output(); rejected -> fallback
#   6. on_event hook (provider, model, purpose, tokens, latency, outcome)

from __future__ import annotations

import logging
import threading
import time
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from navi.data.messages import QA_COOLDOWN_MESSAGES, QA_DAILY_CAP_MESSAGES
from navi.llm import safety
from navi.llm.base import LLMError, LLMProvider, LLMRequest, LLMResponse
from navi.llm.gemini import DEFAULT_RETRY_AFTER

logger = logging.getLogger("navi.llm.router")

_IST = timezone(timedelta(hours=5, minutes=30))
USER_LIMITED = {"qa", "context_reply"}       # purposes subject to the per-user cooldown and daily cap
LONG_PURPOSES = {"summary", "mod"}           # get 4x the output-token budget

PRIORITY = {"qa": 0, "context_reply": 0, "summary": 1, "mod": 1,
            "prediction": 2, "vibe": 3, "template_batch": 3}
CACHEABLE = {"prediction"}  # only /navi predictions may fall back to the template pool

BREAKER_FAILURE_THRESHOLD = 3     # consecutive server failures
BREAKER_OPEN_SECONDS = 300.0      # 5 minutes, then one half-open probe
CONFIG_LOG_INTERVAL = 600.0       # log config errors at most every 10 minutes
CONFIG_ALERT_INTERVAL = 3600.0    # DM the owner at most once an hour


class CircuitBreaker:
    """closed -> (3 consecutive failures | immediate trip) -> open -> (timeout) -> half-open probe."""

    def __init__(
        self,
        threshold: int = BREAKER_FAILURE_THRESHOLD,
        open_seconds: float = BREAKER_OPEN_SECONDS,
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


@dataclass
class RouterResult:
    text: str
    from_cache: bool      # True when the text is a cached template or the caller's fallback (not a live reply)
    outcome: str          # ok | off | budget | breaker | cooldown | error | empty | safety
    provider: str = ""
    model: str = ""


class LLMRouter:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        cache_lookup: Callable[[str, str, str | None], str | None] | None = None,
        rpm_limit: int = 10,
        free_tier_mode: bool = True,
        yield_below_fraction: float = 0.0,
        settings=None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self._cache_lookup = cache_lookup  # (cache_type, name, curse_used) -> personalised text | None
        self.rpm_limit = rpm_limit
        self.free_tier_mode = free_tier_mode
        self.yield_below_fraction = yield_below_fraction  # 0 = never yield (Phase 2 keeps today's behaviour)
        self._clock = clock
        self._settings = settings   # navi.settings.store.Settings; None = use the constructor values only

        self.daily_calls = 0                       # provider calls today (IST); seed_daily_calls() restores it at startup
        self._daily_date = self._today()
        self._user_last: dict[int, float] = {}     # user_id -> clock() of their last limited call
        self._user_day: dict[int, tuple[str, int]] = {}   # user_id -> (IST date, calls)

        self.enabled = True
        self.free_only = False
        self.breaker = CircuitBreaker(clock=clock)
        self._key_cooldown: dict[str, float] = {}
        self._last_config_log = -CONFIG_LOG_INTERVAL
        self._last_config_alert = -CONFIG_ALERT_INTERVAL
        # Set by the app; called from the event loop with a short message for the owner.
        self.on_config_error: Callable[[str], None] | None = None
        self.on_event: Callable[[dict], None] | None = None

        self._window_start = time.monotonic()
        self._request_count = 0
        self.active_key = "none"
        self.calls: dict[str, int] = {k: 0 for k in provider.key_names}
        self.failed_calls = 0

    # ------------------------------------------------------------------
    # Introspection (used by /admin status)
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self.provider.model

    @property
    def is_circuit_open(self) -> bool:
        return self.breaker.is_open

    @property
    def failure_count(self) -> int:
        return self.breaker.failures

    @property
    def open_until(self) -> datetime | None:
        left = self.breaker.seconds_left
        return datetime.now() + timedelta(seconds=left) if left > 0 else None

    # ------------------------------------------------------------------
    # Live settings (read at use time, so /admin changes apply immediately)
    # ------------------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return datetime.now(_IST).strftime("%Y-%m-%d")

    def _setting(self, key: str, fallback):
        return self._settings.get(key) if self._settings is not None else fallback

    @property
    def is_enabled(self) -> bool:
        return self.enabled and self._setting("ai.provider", "gemini") != "off"

    @property
    def is_free_only(self) -> bool:
        return self.free_only or self._setting("ai.gemini_keys", "free_then_paid") == "free_only"

    @property
    def rpm(self) -> int:
        return int(self._setting("ai.rpm_budget", self.rpm_limit))

    def seed_daily_calls(self, count: int) -> None:
        self._daily_date, self.daily_calls = self._today(), count

    def _roll_day(self) -> None:
        today = self._today()
        if today != self._daily_date:
            self._daily_date, self.daily_calls = today, 0

    def _tune(self, req: LLMRequest) -> LLMRequest:
        """Apply ai.temperature / ai.max_output_tokens / ai.model from the settings."""
        if self._settings is None:
            return req
        override = self._settings.get("ai.model")
        if override and override != self.provider.model:
            self.provider.model = override
        tokens = int(self._settings.get("ai.max_output_tokens")) * (4 if req.purpose in LONG_PURPOSES else 1)
        return replace(req, temperature=float(self._settings.get("ai.temperature")), max_tokens=tokens)

    def _user_limited(self, req: LLMRequest, user_id: int | None) -> str | None:
        """Return 'cooldown' or 'daily_cap' when this user may not ask again yet (qa / context replies only)."""
        if self._settings is None or user_id is None or req.purpose not in USER_LIMITED:
            return None
        now, today = self._clock(), self._today()
        cooldown = self._settings.get("ai.qa_cooldown_seconds")
        if cooldown and now - self._user_last.get(user_id, -1e12) < cooldown:
            return "cooldown"
        day, used = self._user_day.get(user_id, (today, 0))
        if day != today:
            used = 0
        if used >= self._settings.get("ai.qa_daily_cap"):
            return "daily_cap"
        self._user_last[user_id] = now
        self._user_day[user_id] = (today, used + 1)
        return None

    def status_dict(self) -> dict:
        free = self.calls.get("free", 0)
        paid = self.calls.get("paid", 0)
        total = free + paid + self.failed_calls
        self._refresh_window()
        now = self._clock()
        return {
            "model": self.model,
            "circuit_open": self.is_circuit_open,
            "failure_count": self.failure_count,
            "open_until": self.open_until.isoformat() if self.open_until else "N/A",
            "active_key": self.active_key,
            "free_key_available": "free" in self.provider.key_names,
            "paid_key_available": "paid" in self.provider.key_names,
            "cooldowns": {k: int(v - now) for k, v in self._key_cooldown.items() if v > now},
            "circuit_seconds_left": int(self.breaker.seconds_left),
            "free_calls": free,
            "paid_calls": paid,
            "failed_calls": self.failed_calls,
            "total_calls": total,
            "free_pct": round(free / total * 100) if total else 0,
            "paid_pct": round(paid / total * 100) if total else 0,
            "rpm_used": self._request_count,
            "rpm_limit": self.rpm,
            "daily_calls": self.daily_calls,
            "daily_call_cap": self._setting("ai.daily_call_cap", None),
            "provider_setting": self._setting("ai.provider", "gemini"),
            "window_resets_in_seconds": max(0, 60 - int(time.monotonic() - self._window_start)),
            "free_tier_mode": self.free_tier_mode,
        }

    # ------------------------------------------------------------------
    # Startup check
    # ------------------------------------------------------------------

    async def verify(self) -> str:
        """Run the provider's model check (if it has one) and handle a configuration failure."""
        import asyncio

        check = getattr(self.provider, "verify_model_sync", None)
        if check is None:
            return self.model
        model, err = await asyncio.get_running_loop().run_in_executor(None, check)
        if err is not None:
            if err.kind == "config":
                self._handle_config_error("startup model check", err)
            else:
                logger.warning("Could not verify model (%s); keeping %s.", err, model)
        return model

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    async def generate(
        self,
        req: LLMRequest,
        *,
        fallback: str,
        user_id: int | None = None,
        name: str = "",
        curse_used: str | None = None,
        cache_type: str | None = None,
        cacheable: bool | None = None,
    ) -> RouterResult:
        """Return a live reply, or `fallback` (never raises). cacheable defaults to purpose in CACHEABLE."""
        use_cache = (req.purpose in CACHEABLE) if cacheable is None else cacheable
        cache_type = cache_type or req.purpose

        async def degraded(outcome: str) -> RouterResult:
            cached = await self._cached(cache_type, name, curse_used) if use_cache else None
            self._emit(req, outcome=outcome)
            return RouterResult(cached or fallback, True, outcome)

        if not self.is_enabled:
            return await degraded("off")

        limited = self._user_limited(req, user_id)
        if limited:
            self._emit(req, outcome="user_" + limited)
            pool = QA_COOLDOWN_MESSAGES if limited == "cooldown" else QA_DAILY_CAP_MESSAGES
            return RouterResult(random.choice(pool).format(user=name or "friend"), True, "user_" + limited)

        req = self._tune(req)
        self._refresh_window()
        self._roll_day()
        cap = self._setting("ai.daily_call_cap", None)
        if cap is not None and self.daily_calls >= cap:
            logger.warning("Daily LLM call cap reached (%d).", cap)
            return await degraded("cap")
        if self._request_count >= self.rpm:
            logger.warning("Rate limit hit (%d/%d RPM). Serving fallback.", self._request_count, self.rpm)
            return await degraded("budget")
        left = 1 - self._request_count / self.rpm
        if PRIORITY.get(req.purpose, 1) >= 2 and left < self.yield_below_fraction:
            return await degraded("budget")

        if not self.breaker.allow():
            logger.warning("Circuit OPEN - fallback mode for ~%d more seconds.", int(self.breaker.seconds_left))
            return await degraded("breaker")

        self._request_count += 1
        self.daily_calls += 1
        keys = [k for k in self.provider.key_names
                if not (self.is_free_only and k in getattr(self.provider, "paid_keys", ()))]

        server_failure = False
        tried = False
        for key in keys:
            if self._clock() < self._key_cooldown.get(key, 0.0):
                continue
            tried = True
            try:
                resp = await self.provider.generate(req, key)
            except LLMError as err:
                if err.kind == "rate_limited":
                    delay = err.retry_after or DEFAULT_RETRY_AFTER
                    self._key_cooldown[key] = self._clock() + delay
                    logger.warning("%s %s key rate limited; cooling down %.0fs.", self.provider.name, key, delay)
                    continue
                if err.kind == "config":
                    self._handle_config_error(f"{key} key", err)
                    self.failed_calls += 1
                    self.active_key = "none"
                    return await degraded("error")
                logger.warning("%s %s key server error: %s", self.provider.name, key, err)
                server_failure = True
                continue
            if resp.text:
                ok, reason = safety.check_output(resp.text, req.purpose)
                self.breaker.record_success()
                self.active_key = key
                self.calls[key] = self.calls.get(key, 0) + 1
                if not ok:
                    logger.warning("Reply rejected by safety filter (%s).", reason)
                    self._emit(req, resp, outcome="safety")
                    return RouterResult(fallback, True, "safety", resp.provider, resp.model)
                self._emit(req, resp, outcome="ok")
                return RouterResult(resp.text, False, "ok", resp.provider, resp.model)
            logger.warning("%s %s key returned an empty response.", self.provider.name, key)

        self.failed_calls += 1
        self.active_key = "none"
        if server_failure:
            self.breaker.record_failure()
            logger.error("Server failure. Breaker failures: %d/%d", self.breaker.failures, self.breaker.threshold)
        else:
            if not tried:
                logger.warning("All keys are cooling down after rate limits.")
            self.breaker.release_probe()
        return await degraded("error" if tried else "cooldown")

    async def cache_only(self, cache_type: str, name: str, fallback: str, curse_used: str | None = None) -> RouterResult:
        """Serve straight from the template pool without touching the provider (3rd+ call in a minute)."""
        cached = await self._cached(cache_type, name, curse_used)
        return RouterResult(cached or fallback, True, "cache")

    async def _cached(self, cache_type: str, name: str, curse_used: str | None) -> str | None:
        """Template-pool lookup, run off the event loop (it is a SQLite read)."""
        if self._cache_lookup is None:
            return None
        import asyncio

        return await asyncio.get_running_loop().run_in_executor(None, self._cache_lookup, cache_type, name, curse_used)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh_window(self) -> None:
        if time.monotonic() - self._window_start >= 60:
            self._window_start = time.monotonic()
            self._request_count = 0

    def _handle_config_error(self, where: str, err: LLMError) -> None:
        now = self._clock()
        if now - self._last_config_log >= CONFIG_LOG_INTERVAL:
            self._last_config_log = now
            logger.error("%s configuration error (%s, model=%s): %s", self.provider.name, where, self.model, err)
        if self.on_config_error and now - self._last_config_alert >= CONFIG_ALERT_INTERVAL:
            self._last_config_alert = now
            try:
                self.on_config_error(
                    f"{self.provider.name} config error ({where}, model `{self.model}`): {str(err)[:300]}. "
                    f"Check the API key / model setting. Falling back to cached/canned replies until fixed."
                )
            except Exception:
                logger.exception("Owner alert callback failed.")
        self.breaker.trip()

    def _emit(self, req: LLMRequest, resp: LLMResponse | None = None, *, outcome: str) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event({
                "provider": resp.provider if resp else self.provider.name,
                "model": resp.model if resp else self.model,
                "purpose": req.purpose,
                "input_tokens": resp.input_tokens if resp else 0,
                "output_tokens": resp.output_tokens if resp else 0,
                "latency_ms": resp.latency_ms if resp else 0,
                "outcome": outcome,
            })
        except Exception:
            logger.exception("on_event hook failed.")
