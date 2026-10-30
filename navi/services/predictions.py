# navi/services/predictions.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timedelta, timezone

from navi.data.glossary import RASHIS
from navi.data.messages import FALLBACK_MESSAGES, SPAM_WRAPPERS
from navi.db.repos.content import (
    get_cached_prediction,
    get_last_n_predictions,
    get_todays_user_prediction,
    save_user_prediction,
)
from navi.db.repos.users import get_user_profile, increment_prediction_count, upsert_user
from navi.llm.base import LLMRequest
from navi.llm.prompts import get_navi_prompt, get_time_aware_system_prompt
from navi.services.template_pool import store_generated

logger = logging.getLogger("navi.services.predictions")


def get_user_minute_count(ctx, user_id: int, increment: bool = True) -> int:
    """Return how many times user has used /navi in the last limit.navi_cooldown_seconds (default 60).

    If increment=True, also records this usage (call ONCE per invocation).
    Returns the count AFTER incrementing.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ctx.settings.get("limit.navi_cooldown_seconds"))

    # Clean expired timestamps
    ctx.state.user_usage.setdefault(user_id, [])
    ctx.state.user_usage[user_id] = [t for t in ctx.state.user_usage[user_id] if t > cutoff]

    if increment:
        ctx.state.user_usage[user_id].append(now)

    return len(ctx.state.user_usage[user_id])




async def get_navi_prediction(ctx, user_id: int, name: str, usage_count: int = 1) -> str:
    """Get a Navi prediction.

    Routing by usage_count within the current minute:
      1st call  → normal flow (50% daily cache reuse, otherwise Gemini)
      2nd call  → 35% daily cache, 65% Gemini
      3rd+ call → always daily/pool cache with artificial delay (no API)
    """
    profile = get_user_profile(ctx.db, user_id)

    # Assign Rashi if missing (new user, or existing user from before Rashi was introduced)
    rashi: str | None = None if profile is None else profile.get("rashi")
    if not rashi:
        rashi = random.choice(RASHIS)
        upsert_user(ctx.db, user_id, name, rashi=rashi)
        logger.info("Assigned Rashi to %s: %s", name, rashi)

    todays_pred = get_todays_user_prediction(ctx.db, user_id)

    # ---- 3rd+ usage: always serve from cache, never call Gemini ----
    if usage_count >= 3:
        if todays_pred:
            await asyncio.sleep(random.uniform(1.5, 3.0))  # feel like AI
            return todays_pred
        # No daily cache yet — fall through to pool cache only (no Gemini)
        cached_pool = (await ctx.llm.cache_only("navi", name, random.choice(FALLBACK_MESSAGES))).text
        await asyncio.sleep(random.uniform(1.5, 3.0))
        return cached_pool

    # ---- 2nd usage: 35% daily cache, 65% Gemini ----
    if usage_count == 2 and todays_pred:
        if random.random() < 0.35:
            logger.info("2nd call: serving cached prediction for %s", name)
            await asyncio.sleep(random.uniform(1.0, 2.5))
            return todays_pred

    # ---- 1st usage (or 2nd fell through): normal 50% daily cache check ----
    if usage_count == 1 and todays_pred:
        cache_chance = ctx.settings.get("chance.cache_reuse")
        if random.random() < cache_chance:
            logger.info("Recycling today's prediction from cache for %s", name)
            await asyncio.sleep(random.uniform(1.0, 2.5))
            return todays_pred

    # ---- Gemini call ----
    past_predictions = get_last_n_predictions(ctx.db, user_id, n=3)
    system_prompt = get_time_aware_system_prompt(ctx.db, username=name)
    user_prompt = get_navi_prompt(name, rashi=rashi, past_predictions=past_predictions)

    res = await ctx.llm.generate(
        LLMRequest(purpose="prediction", system=system_prompt, prompt=user_prompt),
        cache_type="navi",
        name=name,
        fallback=random.choice(FALLBACK_MESSAGES),
    )
    result, from_cache = res.text, res.from_cache

    if not from_cache and result not in FALLBACK_MESSAGES:
        template = templatize(result, name)
        store_generated(ctx, "prediction", template)      # safety-checked; pending review unless auto-approve is on
        save_user_prediction(ctx.db, user_id, result)
        increment_prediction_count(ctx.db, user_id)

    return result


def make_cache_lookup(db):
    """Template-pool lookup used by the LLM router for cacheable purposes (/navi predictions)."""

    def lookup(cache_type: str, name: str, curse_used: str | None = None) -> str | None:
        template = get_cached_prediction(db(), cache_type, min_count=20)
        if not template:
            return None
        result = template.replace("{user}", name)
        if curse_used:
            result = result.replace("{curse}", curse_used)
        return result

    return lookup


def templatize(text: str, name: str, curse: str | None = None) -> str:
    """Replace concrete name/curse with {user}/{curse} placeholders for caching."""
    result = text.replace(name, "{user}")
    if curse:
        result = result.replace(curse, "{curse}")
    return result


def _personalise(template: str, name: str, curse: str | None = None) -> str:
    """Fill {user}/{curse} placeholders with real values."""
    result = template.replace("{user}", name)
    if curse:
        result = result.replace("{curse}", curse)
    return result


def format_cached_spam_reply(cached: str, name: str) -> str:
    """Strip the 'Eda/Aiyo [name],' opener from a cached prediction and
    wrap it in a varied snarky spam-reply message."""
    # Remove leading opener like "Eda Link," / "Aiyo Link," (case-insensitive)
    stripped = re.sub(
        rf"^(Hey|Oh|Eda|Aiyo)\s+{re.escape(name)}\s*[,!.]?\s*",
        "",
        cached,
        flags=re.IGNORECASE,
    ).strip()
    # Capitalise first letter of remainder
    if stripped:
        stripped = stripped[0].upper() + stripped[1:]
    prediction_text = stripped or cached  # fall back to full text if strip failed
    wrapper = random.choice(SPAM_WRAPPERS)
    return wrapper.format(prediction=prediction_text)
