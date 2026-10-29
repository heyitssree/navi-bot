# navi/handlers/passive_curse.py - moved from bot.py on_message (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random

import discord

from navi.data.curse_data import contains_curse_word, get_random_curse_back, get_random_doomed_prediction
from navi.data.messages import FALLBACK_MESSAGES
from navi.db.repos.content import save_prediction
from navi.db.repos.points import log_curse
from navi.db.repos.settings import get_config_float, get_config_int
from navi.llm.base import LLMRequest
from navi.llm.prompts import get_curse_prompt, get_time_aware_system_prompt
from navi.services.points import add_experience, update_boli_points
from navi.services.predictions import templatize

logger = logging.getLogger("navi.handlers.passive_curse")


async def handle_passive_curse(ctx, message: discord.Message) -> bool:
    """Passive curse word reply (+1 Boli, LLM line with fallback templates)."""
    # ---- Passive curse word reply ----
    curse_chance = get_config_float(ctx.db, "curse_reply_chance", 0.25)
    _curse_matched, curse_used = contains_curse_word(message.content)
    if get_config_int(ctx.db, "feature_curse_replies", 1) and _curse_matched and random.random() < curse_chance:
        username = message.author.display_name
        user_id = message.author.id
        curse_used = curse_used or "that"

        log_curse(ctx.db, user_id, username, curse_used)
        update_boli_points(ctx.db, user_id, 1)  # +1 Boli pt for curse event
        add_experience(ctx.db, user_id, 1)

        system_prompt = get_time_aware_system_prompt(ctx.db, username=username)
        user_prompt = get_curse_prompt(username, curse_used)

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(1.0, 2.0))
            _res = await ctx.llm.generate(
                LLMRequest(purpose="qa", system=system_prompt, prompt=user_prompt),
                fallback=random.choice(FALLBACK_MESSAGES),
                name=username,
                cache_type="curse",
                curse_used=curse_used,
            )
            reply, from_cache = _res.text, _res.from_cache

        if reply in FALLBACK_MESSAGES:
            reply = (
                get_random_doomed_prediction(username)
                if random.random() < 0.5
                else get_random_curse_back(username)
            )
        elif not from_cache:
            template = templatize(reply, username, curse_used)
            save_prediction(ctx.db, "curse", template, user_id=message.author.id)

        await message.reply(reply)
    return False

