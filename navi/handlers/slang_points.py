# navi/handlers/slang_points.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord

from navi.data.curse_data import contains_boli_trigger
from navi.services.levels import maybe_announce_levelup
from navi.services.points import award
from navi.services.slang_scorer import get_slang_matches, score_message

logger = logging.getLogger("navi.handlers.slang_points")












def _check_slang_spam(ctx, user_id: int, content: str) -> bool:
    """Track short standalone messages regardless of word change.

    Returns True (suppress Boli points) if:
    - The user is currently in a 5-minute slang cooldown, OR
    - This message is the 3rd+ consecutive short message within 60s,
      which also starts the 5-minute cooldown.

    Counter increments for ANY short message within the 60s window,
    even if the user switches to a different word.
    """
    now = datetime.now(timezone.utc)

    # Check if already in cooldown
    cooldown_until = ctx.state.slang_cooldown.get(user_id)
    if cooldown_until and now < cooldown_until:
        return True  # still cooling down — suppress points

    # Count consecutive short messages within the window
    count, last_time = ctx.state.slang_spam_tracker.get(user_id, (0, now))
    within_window = (now - last_time).total_seconds() <= ctx.settings.get("slang.spam_window_seconds")

    new_count = count + 1 if within_window else 1
    ctx.state.slang_spam_tracker[user_id] = (new_count, now)

    if new_count >= ctx.settings.get("slang.spam_threshold") + 1:
        # Enter 5-minute cooldown
        ctx.state.slang_cooldown[user_id] = now + timedelta(minutes=ctx.settings.get("slang.cooldown_minutes"))
        logger.debug(
            "Slang spam cooldown set for user_id=%d — '%s' was the %d-th short msg in window.",
            user_id, content.strip()[:20], new_count,
        )
        return True

    return False


async def handle_slang_points(ctx, message: discord.Message) -> bool:
    """Boli points for local slang triggers and the slang dictionary (with spam gate)."""
    # ---- Slang Spam Prevention: gate Boli awards for repeat short messages ----
    # Check BEFORE awarding points. If this is a repeated standalone word/phrase
    # (same content, <=2 words, sent 3+ times within 60s), suppress all point awards.
    _stripped = message.content.strip()
    _words = _stripped.split()
    _is_slang_spam = (
        len(_words) <= ctx.settings.get("slang.max_words")
        and len(_stripped) <= ctx.settings.get("slang.max_chars")
        and bool(_stripped)
        and _check_slang_spam(ctx, message.author.id, _stripped)
    )

    # ---- Boli Points: local slang triggers ----
    triggered_words = contains_boli_trigger(message.content) if ctx.settings.get("feature.boli_points") else []
    if triggered_words and not _is_slang_spam:
        points = len(triggered_words) * 5
        award(ctx.db, message.author.id, points, points, reason="slang", detail=",".join(triggered_words))
        await maybe_announce_levelup(ctx, 
            message.author.mention, message.author.id, message.channel
        )
        logger.debug(
            "%s triggered Boli words %s → +%d pts",
            message.author.display_name, triggered_words, points
        )

    # ---- Slang Dictionary Scoring (TVM +pts / Kochi -pts, tiered) ----
    if ctx.settings.get("feature.boli_points") and not _is_slang_spam:
        slang_delta = score_message(message.content)
        if slang_delta != 0:
            award(ctx.db, message.author.id, slang_delta, max(0, slang_delta), reason="slang", detail="dictionary")
            if slang_delta > 0:
                await maybe_announce_levelup(ctx, 
                    message.author.mention, message.author.id, message.channel
                )
            matches = get_slang_matches(message.content)
            logger.debug(
                "%s slang score %+d pts — matches: %s",
                message.author.display_name,
                slang_delta,
                [(m["token"], m["region"], m["points"]) for m in matches],
            )
    return False

