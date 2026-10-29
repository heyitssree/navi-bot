# navi/services/levels.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import random

import discord

from navi.data.messages import LEVEL_UP_MESSAGES
from navi.db.repos.points import get_experience, get_level_from_points

_LEVEL_TITLES: dict[int, str] = {
    0:   "Tourist",
    5:   "Chalai Wanderer",
    10:  "Thampanoor Regular",
    15:  "Auto Stand VIP",
    20:  "Palayam Negotiator",
    25:  "Kowdiar Cruiser",
    30:  "Chaya Kada Analyst",
    35:  "Technopark Hustler",
    40:  "KSRTC Minnal Survivor",
    45:  "Ponmudi Rider",
    50:  "Secretariat Insider",
    55:  "Putharikandam Orator",
    60:  "Padmanabhaswamy Guard",
    65:  "East Fort Navigator",
    70:  "Varkala Drifter",
    75:  "Museum Campus Walker",
    80:  "Trivandrum Oracle",
    85:  "The Southern Sage",
    90:  "Ananthapuri Legend",
    95:  "Cosmic Malayali",
    100: "The Chosen One",
}


def get_level_title(level: int) -> str:
    """Return the highest title whose threshold is <= level."""
    title = _LEVEL_TITLES[0]
    for threshold in sorted(_LEVEL_TITLES):
        if level >= threshold:
            title = _LEVEL_TITLES[threshold]
    return title


async def maybe_announce_levelup(ctx, mention: str,
    user_id: int,
    channel: discord.abc.Messageable,
) -> None:
    """Send a level-up notification if the user just crossed a level threshold.

    Level is now derived from XP (experience column), never from boli_points.
    """
    xp = get_experience(ctx.db, user_id)
    level = get_level_from_points(xp)

    # Check if we've crossed a new level since last time (stored in-memory)
    prev_level = ctx.state.user_level_cache.get(user_id, -1)
    if level <= prev_level:
        return
    ctx.state.user_level_cache[user_id] = level
    if prev_level == -1:
        return  # first time seen — don't announce retroactively

    old_title = get_level_title(prev_level if prev_level >= 0 else 0)
    new_title = get_level_title(level)

    msg = f"🔥 **Level Up!** {mention} reached **Level {level}**! Keep the boli flowing!"
    if new_title != old_title:
        flavour = random.choice(LEVEL_UP_MESSAGES).format(user=mention, level=level)
        msg = (
            f"🔥 **Level Up!** {mention} reached **Level {level}**! "
            f"Earned title: [**{new_title}**]. Keep the boli flowing!\n"
            f"*{flavour}*"
        )

    await channel.send(msg)
