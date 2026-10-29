# navi/handlers/owner_text.py - moved from bot.py on_message (behaviour unchanged)
from __future__ import annotations

import logging

import discord

logger = logging.getLogger("navi.handlers.owner_text")


async def handle_owner_toggle(ctx, message: discord.Message) -> bool:
    """Owner text commands: "navi syros stop|start" toggles Free-Only API mode."""
    content_lower = message.content.strip().lower()
    # ---- Admin toggle ----
    if content_lower in ("navi syros stop", "navi syros start"):
        app_info = await ctx.bot.application_info()
        if message.author.id == app_info.owner.id:
            ctx.llm.free_only = content_lower == "navi syros stop"
            status = "now running in Free-Only Mode (will fallback to cache if free key fails)." if ctx.llm.free_only else "Gemini Paid Tier is back online."
            await message.reply(f"Ok owner, {status}")
        return True
    return False

