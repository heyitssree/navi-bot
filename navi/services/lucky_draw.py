# navi/services/lucky_draw.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import discord

from navi.db.repos.settings import get_config_str, set_config_str
from navi.db.repos.users import get_active_user_ids_previous_day, get_top_n_from_user_ids
from navi.services.points import award

logger = logging.getLogger("navi.services.lucky_draw")


_LUCKY_DRAW_AMOUNT = 200


_LUCKY_DRAW_MESSAGES: list[str] = [
    "🪐 **Daily Navi Lucky Draw!** The cosmos took one look at the leaderboard, scratched its head, and said: {winner_mention}, it's your lucky day! **+{amount} Boli** for doing absolutely nothing productive. 🎉",
    "🎰 **Ding ding ding!** Today's cosmic jackpot winner is {winner_mention}! The stars rolled the dice, picked a name, and landed on yours. Congrats, you beautifully undeserving human. **+{amount} Boli** added! 🦄",
    "🌈 **Navi Lucky Draw Results:** After careful scientific analysis (aka pure random chance), the universe has decided {winner_mention} deserves **{amount} free Boli**. No skill required. The cosmos is chaotic like that. 🍀",
    "✨ **Lucky Draw o’clock!** {winner_mention} woke up, existed, and was randomly chosen by Navi. The reward? **+{amount} Boli**. The lesson? Sometimes just being here is enough. Spend it on something silly. 🪄",
    "💫 **Breaking news from the Cosmic Lottery Bureau:** {winner_mention} is today’s winner! Out of everyone who was active yesterday, Navi spun the wheel and — yep, it’s you. **{amount} Boli** deposited into your cosmic wallet. Go gamble it immediately. 🎨",
    "🔮 **The oracle has spoken!** Navi closed her eyes, pointed at the leaderboard, and her finger landed on {winner_mention}. **+{amount} Boli** for being in the right chat at the right time. May the Boli bless your evening. 🙏",
]


async def lucky_draw_loop(ctx) -> None:
    """Background loop that fires a lucky draw at 7:00am IST every day.

    Picks one random user from the top-10 most-active previous day members
    and awards _LUCKY_DRAW_AMOUNT Boli Points. Announced in the general channel.
    """
    _IST = timezone(timedelta(hours=5, minutes=30))

    while True:
        # Calculate seconds until next 7:00am IST
        now_ist = datetime.now(_IST)
        target = now_ist.replace(hour=7, minute=0, second=0, microsecond=0)
        if now_ist >= target:
            target = target + timedelta(days=1)
        wait_seconds = (target - now_ist).total_seconds()
        logger.info("Lucky draw sleeping for %.0f seconds (until 7:00am IST).", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            # Deduplicate: check we haven't already run today
            today_str = datetime.now(_IST).strftime("%Y-%m-%d")
            last_run = get_config_str(ctx.db, "lucky_draw_last_date", "")
            if last_run == today_str:
                logger.info("Lucky draw already ran today (%s) — skipping.", today_str)
                await asyncio.sleep(60)  # small extra sleep to avoid re-triggering
                continue

            result = await run_lucky_draw(ctx)
            logger.info("Lucky draw loop: %s", result)

        except Exception as exc:
            logger.error("Lucky draw loop error: %s", exc)

        await asyncio.sleep(60)  # small buffer before recalculating next target


async def run_lucky_draw(ctx, announce_channel: discord.abc.Messageable | None = None) -> str:
    """Core lucky-draw logic. Returns a status string for logging/feedback.

    Can be called from the scheduled loop or the /lucky_draw slash command.
    If announce_channel is provided it overrides the default channel resolution.
    """
    _IST = timezone(timedelta(hours=5, minutes=30))
    today_str = datetime.now(_IST).strftime("%Y-%m-%d")

    active_ids = get_active_user_ids_previous_day(ctx.db)
    if not active_ids:
        return "No active users from the previous day — draw skipped."

    candidates = get_top_n_from_user_ids(ctx.db, active_ids, n=10)
    if not candidates:
        return "No top-10 candidates found — draw skipped."

    winner = random.choice(candidates)
    award(ctx.db, winner["user_id"], _LUCKY_DRAW_AMOUNT, _LUCKY_DRAW_AMOUNT, reason="lucky_draw")
    set_config_str(ctx.db, "lucky_draw_last_date", today_str)

    winner_mention = f"<@{winner['user_id']}>"
    msg = random.choice(_LUCKY_DRAW_MESSAGES).format(
        winner_mention=winner_mention,
        amount=_LUCKY_DRAW_AMOUNT,
    )

    if announce_channel is None:
        _NAVI_GAMES_ID = 1499827359585665104
        _BOT_COMMANDS_ID = 1372128042058780783
        announce_channel = (
            ctx.bot.get_channel(_NAVI_GAMES_ID)
            or discord.utils.find(
                lambda c: c.name == "navi-games",
                (ch for g in ctx.bot.guilds for ch in g.text_channels),
            )
            or ctx.bot.get_channel(_BOT_COMMANDS_ID)
        )

    if announce_channel:
        await announce_channel.send(msg)
        logger.info(
            "Lucky draw winner: %s (user_id=%d) +%d Boli — announced in #%s.",
            winner["username"], winner["user_id"], _LUCKY_DRAW_AMOUNT,
            getattr(announce_channel, "name", "?"),
        )
        return f"Winner: {winner['username']} (+{_LUCKY_DRAW_AMOUNT} Boli)"
    else:
        logger.warning("Lucky draw: could not find any announce channel.")
        return f"Winner: {winner['username']} (+{_LUCKY_DRAW_AMOUNT} Boli) — no announce channel found."
