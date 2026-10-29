# navi/handlers/slang_points.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord

from navi.data.curse_data import contains_boli_trigger
from navi.db.repos.settings import get_config_int
from navi.services.levels import maybe_announce_levelup
from navi.services.points import add_experience, update_boli_points
from navi.services.slang_scorer import get_slang_matches, score_message

logger = logging.getLogger("navi.handlers.slang_points")


_SLANG_SPAM_WINDOW_SECONDS = 60   # window for consecutive short-message counting


_SLANG_SPAM_THRESHOLD = 2          # trigger cooldown after this many (3rd message = index 2)


_SLANG_COOLDOWN_MINUTES = 5        # how long points are suppressed after trigger


_SLANG_SPAM_MAX_WORDS = 2          # only track messages with ≤ this many words


_SLANG_SPAM_MAX_CHARS = 20         # and ≤ this many chars


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
    within_window = (now - last_time).total_seconds() <= _SLANG_SPAM_WINDOW_SECONDS

    new_count = count + 1 if within_window else 1
    ctx.state.slang_spam_tracker[user_id] = (new_count, now)

    if new_count >= _SLANG_SPAM_THRESHOLD + 1:
        # Enter 5-minute cooldown
        ctx.state.slang_cooldown[user_id] = now + timedelta(minutes=_SLANG_COOLDOWN_MINUTES)
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
        len(_words) <= _SLANG_SPAM_MAX_WORDS
        and len(_stripped) <= _SLANG_SPAM_MAX_CHARS
        and bool(_stripped)
        and _check_slang_spam(ctx, message.author.id, _stripped)
    )

    # ---- Boli Points: local slang triggers ----
    triggered_words = contains_boli_trigger(message.content) if get_config_int(ctx.db, "feature_boli_points", 1) else []
    if triggered_words and not _is_slang_spam:
        points = len(triggered_words) * 5
        update_boli_points(ctx.db, message.author.id, points)
        add_experience(ctx.db, message.author.id, points)
        await maybe_announce_levelup(ctx, 
            message.author.mention, message.author.id, message.channel
        )
        logger.debug(
            "%s triggered Boli words %s → +%d pts",
            message.author.display_name, triggered_words, points
        )

    # ---- Slang Dictionary Scoring (TVM +pts / Kochi -pts, tiered) ----
    if get_config_int(ctx.db, "feature_boli_points", 1) and not _is_slang_spam:
        slang_delta = score_message(message.content)
        if slang_delta != 0:
            update_boli_points(ctx.db, message.author.id, slang_delta)
            if slang_delta > 0:
                add_experience(ctx.db, message.author.id, slang_delta)
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

