# navi/handlers/vibe.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

from navi.services.mentions import nobody

import logging
from collections import deque
from datetime import datetime, timezone

import discord

from navi.data.curse_data import SEVERE_CURSE_RE
from navi.llm.base import LLMRequest
from navi.llm.prompts import get_time_aware_system_prompt, get_vibe_check_prompt

logger = logging.getLogger("navi.handlers.vibe")










def _is_heated_message(content: str) -> bool:
    """Return True if the message is all-caps or contains a severe curse word."""
    is_allcaps = len(content) > 3 and content == content.upper() and content.strip().isalpha() is False and any(c.isalpha() for c in content)
    has_severe = SEVERE_CURSE_RE.search(content) is not None
    return is_allcaps or has_severe


async def _check_vibe(ctx, message: discord.Message) -> None:
    """Track message and fire vibe-check calming message if chat overheats."""
    channel_id = message.channel.id
    now = datetime.now(timezone.utc)

    # Cooldown guard — don't fire twice in 60s per channel
    last = ctx.state.vibe_last_fired.get(channel_id)
    if last and (now - last).total_seconds() < ctx.settings.get("vibe.cooldown_seconds"):
        return

    # Maintain rolling deque for this channel
    tracker = ctx.state.channel_msg_tracker.setdefault(channel_id, deque())
    tracker.append((now, message.content))

    # Purge messages older than the window
    cutoff = now.timestamp() - ctx.settings.get("vibe.window_seconds")
    while tracker and tracker[0][0].timestamp() < cutoff:
        tracker.popleft()

    if len(tracker) < ctx.settings.get("vibe.min_messages"):
        return

    heated = sum(1 for _, c in tracker if _is_heated_message(c))
    if heated / len(tracker) < ctx.settings.get("vibe.heated_ratio"):
        return

    # Threshold met — fire vibe check
    ctx.state.vibe_last_fired[channel_id] = now
    tracker.clear()

    channel_name = getattr(message.channel, "name", "this channel")
    system_prompt = get_time_aware_system_prompt(ctx.db, username=None)  # no persona for vibe check
    user_prompt = get_vibe_check_prompt(channel_name)

    _res = await ctx.llm.generate(
        LLMRequest(purpose="vibe", system=system_prompt, prompt=user_prompt),
        fallback="Everyone take a breath. Whatever's happening in here, it can wait.",
        name="VibeCheck",
        cache_type="qa",
    )
    reply, _ = _res.text, _res.from_cache
    await message.channel.send(reply, allowed_mentions=nobody())
    logger.info("Vibe check fired in #%s", channel_name)


async def handle_vibe(ctx, message: discord.Message) -> bool:
    """Vibe check: lightweight heat tracker, no API cost unless triggered."""
    # ---- Vibe Check: lightweight heat tracker — no API cost unless triggered ----
    if ctx.settings.get("feature.vibe_check"):
        await _check_vibe(ctx, message)
    return False

