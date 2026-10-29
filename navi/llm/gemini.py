# navi/llm/gemini.py - Gemini provider: free key first, paid key as fallback (the router orders the keys)

from __future__ import annotations

import asyncio
import logging
import os
import re
import time

from google import genai

from navi.llm.base import LLMError, LLMRequest, LLMResponse

logger = logging.getLogger("navi.llm.gemini")

DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.8-flash"
DEFAULT_RETRY_AFTER = 20.0  # seconds, when a 429 carries no retry delay


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


def classify_error(exc: Exception) -> LLMError:
    """Map a google-genai exception onto rate_limited / config / server."""
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return LLMError("rate_limited", str(exc), _retry_delay(exc) or DEFAULT_RETRY_AFTER)
    if code in (400, 401, 403, 404) or status in (
        "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND",
    ):
        return LLMError("config", str(exc))
    # 5xx, timeouts, connection resets, anything unexpected
    return LLMError("server", f"{type(exc).__name__}: {exc}")


class GeminiProvider:
    name = "gemini"
    paid_keys = frozenset({"paid"})  # skipped by the router in Free-Only mode

    def __init__(self, free_api_key: str | None, paid_api_key: str | None, model: str | None = None) -> None:
        if not free_api_key and not paid_api_key:
            raise ValueError(
                "Navi needs at least one Gemini API key. "
                "Set GEMINI_API_KEY_FREE or GEMINI_API_KEY_PAID in .env"
            )
        self._clients: dict[str, genai.Client] = {}
        if free_api_key:
            self._clients["free"] = genai.Client(api_key=free_api_key)
        if paid_api_key:
            self._clients["paid"] = genai.Client(api_key=paid_api_key)
        self.key_names = list(self._clients)
        self.model: str = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
        logger.info("GeminiProvider initialised. Keys: %s, model: %s", self.key_names, self.model)

    # ------------------------------------------------------------------

    async def generate(self, req: LLMRequest, key: str | None = None) -> LLMResponse:
        name = key or self.key_names[0]
        client = self._clients[name]
        started = time.monotonic()
        try:
            response = await asyncio.get_running_loop().run_in_executor(None, self._call, client, req)
        except Exception as exc:
            raise classify_error(exc) from exc
        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            text=response.text or "",
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            provider=self.name,
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _call(self, client: genai.Client, req: LLMRequest):
        logger.debug("Gemini prompt (%s): %.80s...", req.purpose, req.prompt)
        return client.models.generate_content(
            model=self.model,
            contents=req.prompt,
            config={"system_instruction": req.system, "temperature": req.temperature},
        )

    # ------------------------------------------------------------------

    def verify_model_sync(self) -> tuple[str, LLMError | None]:
        """Check the configured model is available to the first key; else switch to FALLBACK_MODEL.

        Returns (active_model, error) where error is set when the listing itself failed.
        """
        client = next(iter(self._clients.values()))
        try:
            available = {m.name.removeprefix("models/") for m in client.models.list()}
        except Exception as exc:
            return self.model, classify_error(exc)
        if self.model not in available:
            logger.error("Configured model %r is not available to this key.", self.model)
            if FALLBACK_MODEL in available and FALLBACK_MODEL != self.model:
                logger.error("Falling back to %s.", FALLBACK_MODEL)
                self.model = FALLBACK_MODEL
            else:
                logger.error("Fallback model %s is not available either; calls will likely fail.", FALLBACK_MODEL)
        logger.info("Active Gemini model: %s", self.model)
        return self.model, None
