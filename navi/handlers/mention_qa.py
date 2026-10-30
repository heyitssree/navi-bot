# navi/handlers/mention_qa.py - bot mention: Q&A (knowledge lookup and answer cache first, then the LLM)
from __future__ import annotations

import asyncio
import logging
import random

import discord

from navi.data.curse_data import contains_curse_word
from navi.services import chat_throttle
from navi.services.mentions import only_user
from navi.services.qa import answer_question, limit_notice_due

logger = logging.getLogger("navi.handlers.mention_qa")


async def handle_mention_qa(ctx, message: discord.Message) -> bool:
    """Bot mention: Q&A."""
    if ctx.bot.user.mentioned_in(message):
        content_without_ping = (
            message.content
            .replace(f"<@{ctx.bot.user.id}>", "")
            .replace(f"<@!{ctx.bot.user.id}>", "")
            .strip()
        )
        if not ctx.settings.get("feature.mention_qa"):
            return True   # switched off: stay silent (and keep the message away from the other handlers)
        if content_without_ping and not contains_curse_word(message.content)[0]:
            verdict = chat_throttle.check(ctx, message.author.id, message.channel.id)
            if verdict == chat_throttle.SILENT:
                return True            # in the quiet period: no AI conversation with this person outside bot-commands
            if verdict == chat_throttle.REDIRECT:
                await message.reply(chat_throttle.redirect_text(ctx, message.author), allowed_mentions=only_user(message.author))
                return True

            async def _do_qa_call():
                await asyncio.sleep(random.uniform(1.0, 2.0))
                return await answer_question(ctx, message, content_without_ping)

            if ctx.config.free_tier_mode:
                async with message.channel.typing():
                    answer = await _do_qa_call()
            else:
                answer = await _do_qa_call()

            if answer.source == "limit" and not limit_notice_due(ctx, message.author.id):
                return True            # one in-character note per window, then silence
            await message.reply(answer.text, allowed_mentions=only_user(message.author))
        # Always return after a mention - never double-trigger slang detection
        return True
    return False
