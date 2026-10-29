# navi/handlers/mention_qa.py - moved from bot.py on_message (behaviour unchanged)
from __future__ import annotations

import asyncio
import logging
import random

import discord

from navi.data.curse_data import contains_curse_word
from navi.data.messages import FALLBACK_MESSAGES
from navi.llm.base import LLMRequest
from navi.llm.prompts import LINK_USERNAME, get_qa_prompt, get_time_aware_system_prompt

logger = logging.getLogger("navi.handlers.mention_qa")


async def handle_mention_qa(ctx, message: discord.Message) -> bool:
    """Bot mention: Q&A."""
    # ---- Bot mention: Q&A ----
    if ctx.bot.user.mentioned_in(message):
        content_without_ping = (
            message.content
            .replace(f"<@{ctx.bot.user.id}>", "")
            .replace(f"<@!{ctx.bot.user.id}>", "")
            .strip()
        )
        if content_without_ping and not contains_curse_word(message.content)[0]:
            system_prompt = get_time_aware_system_prompt(ctx.db, username=message.author.display_name)
            user_prompt = get_qa_prompt(
                message.author.display_name,
                content_without_ping,
                is_link=(message.author.display_name == LINK_USERNAME),
            )

            async def _do_qa_call() -> str:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                _res = await ctx.llm.generate(
                    LLMRequest(purpose="qa", system=system_prompt, prompt=user_prompt),
                    fallback=random.choice(FALLBACK_MESSAGES),
                    name=message.author.display_name,
                    cache_type="qa",
                )
                reply, _ = _res.text, _res.from_cache
                return reply

            if ctx.config.free_tier_mode:
                async with message.channel.typing():
                    reply = await _do_qa_call()
            else:
                reply = await _do_qa_call()

            await message.reply(reply)
        # Always return after a mention — never double-trigger slang detection
        return True
    return False

