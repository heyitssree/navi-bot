# navi/handlers/kochi.py - moved from bot.py on_message (behaviour unchanged)
from __future__ import annotations

import logging
import random

import discord

from navi.data.curse_data import contains_kochi_slang, get_random_kochi_response

logger = logging.getLogger("navi.handlers.kochi")


async def handle_kochi(ctx, message: discord.Message) -> bool:
    """Kochi slang detection: condescending reply with a configurable chance."""
    # ---- Kochi slang detection ----
    kochi_chance = ctx.settings.get("chance.kochi_reply")
    if ctx.settings.get("feature.kochi_replies") and contains_kochi_slang(message.content) and random.random() < kochi_chance:
        response = get_random_kochi_response(message.author.mention)
        await message.reply(response)
        logger.info("Kochi slang detected from %s — condescending reply sent.", message.author.display_name)
        return True
    return False

