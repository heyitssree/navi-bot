# navi/services/owner.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import logging

logger = logging.getLogger("navi.services.owner")


async def dm_owner(ctx, text: str) -> None:
    """Best-effort DM to the bot owner (used for configuration alerts)."""
    try:
        owner_id = ctx.config.owner_id or (await ctx.bot.application_info()).owner.id
        user = await ctx.bot.fetch_user(owner_id)
        await user.send(f"⚠️ {text}")
    except Exception as exc:
        logger.warning("Could not DM owner: %s", exc)
