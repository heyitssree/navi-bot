# navi/handlers/passive_curse.py - passive curse word reply: template-only, no LLM call (Phase 5)
from __future__ import annotations

import asyncio
import logging
import random

import discord

from navi.data.curse_data import contains_curse_word, get_random_doomed_prediction
from navi.services.mentions import only_user
from navi.services.points import award
from navi.services.template_pool import pick

logger = logging.getLogger("navi.handlers.passive_curse")


async def handle_passive_curse(ctx, message: discord.Message) -> bool:
    """A curse-list word in any message: with chance.passive_curse_reply, +1 Boli/XP, log it, and answer with a
    reviewed template (content kind 'curse_back'). Never calls the LLM."""
    curse_chance = ctx.settings.get("chance.passive_curse_reply")
    matched, curse_used = contains_curse_word(message.content)
    if ctx.settings.get("feature.passive_curse_replies") and matched and random.random() < curse_chance:
        username = message.author.display_name
        user_id = message.author.id
        curse_used = curse_used or "that"

        award(ctx.db, user_id, 1, 1, reason="curse_word_said", detail=curse_used, log_only=True)  # +1 Boli, +1 XP

        reply = pick(ctx, "curse_back", user_id, username, curse_used) or get_random_doomed_prediction(username)
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(1.0, 2.0))
        await message.reply(reply, allowed_mentions=only_user(message.author))
    return False
