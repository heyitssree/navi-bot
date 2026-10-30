# navi/handlers/context_reply.py - conversation-aware replies, only in the configured bot-commands channel
#
# Active when feature.context_replies is on, channel.bot_commands is set, the message is in that channel, and it either
# replies to a Navi message or mentions Navi. Context is the reply chain only (at most 4 hops and 1,200 characters,
# never channel history): Navi's own messages and the current user's, minus opted-out users, mentions scrubbed, and
# every line run through the safety filter before it can enter a prompt. Elsewhere, replies to Navi stay ignored.
from __future__ import annotations

import asyncio
import logging
import random
import re

import discord

from navi.data.curse_data import contains_curse_word
from navi.llm import safety
from navi.services.mentions import only_user
from navi.services.qa import answer_question, limit_notice_due

logger = logging.getLogger("navi.handlers.context_reply")

MAX_HOPS = 4
MAX_CHARS = 1200
_MENTION = re.compile(r"<@[!&]?\d+>|<#\d+>|@everyone|@here")


def in_context_channel(ctx, message: discord.Message) -> bool:
    channel_id = ctx.settings.get("channel.bot_commands")
    return bool(ctx.settings.get("feature.context_replies") and channel_id and message.channel.id == channel_id)


async def _parent(message):
    ref = message.reference
    if ref is None:
        return None
    parent = ref.resolved or getattr(ref, "cached_message", None)
    if isinstance(parent, discord.Message):
        return parent
    msg_id = getattr(ref, "message_id", None)
    if msg_id is None:
        return None
    try:
        return await message.channel.fetch_message(msg_id)
    except (discord.HTTPException, AttributeError):
        return None


async def build_history(ctx, message: discord.Message) -> list[tuple[str, str]]:
    """The reply chain above `message` as [(role, text)], oldest first. Roles are 'Navi' and 'User'."""
    out: list[tuple[str, str]] = []
    chars = 0
    current = message
    for _ in range(MAX_HOPS):
        parent = await _parent(current)
        if parent is None:
            break
        current = parent
        author_id = parent.author.id
        if ctx.privacy.is_opted_out(author_id):
            continue
        if author_id == ctx.bot.user.id:
            role = "Navi"
        elif author_id == message.author.id:
            role = "User"
        else:
            continue                                   # other people's messages never enter the prompt
        text = _MENTION.sub("", parent.content).strip()
        if not text or not safety.check_output(text, "context_reply").ok:
            continue
        if chars + len(text) > MAX_CHARS:
            break
        chars += len(text)
        out.append((role, text))
    out.reverse()
    return out


async def handle_context_reply(ctx, message: discord.Message) -> bool:
    """Reply with conversation context in the bot-commands channel. Consumes the message when it applies."""
    if not in_context_channel(ctx, message):
        return False
    parent = await _parent(message)
    replies_to_navi = parent is not None and parent.author.id == ctx.bot.user.id
    mentions_navi = ctx.bot.user.mentioned_in(message)
    if not (replies_to_navi or mentions_navi):
        return False

    question = message.content.replace(f"<@{ctx.bot.user.id}>", "").replace(f"<@!{ctx.bot.user.id}>", "").strip()
    if not question or contains_curse_word(message.content)[0]:
        return True
    history = await build_history(ctx, message)

    async def work():
        await asyncio.sleep(random.uniform(1.0, 2.0))
        return await answer_question(ctx, message, question, history=history, purpose="context_reply")

    async with message.channel.typing():
        answer = await work()
    if answer.source == "limit" and not limit_notice_due(ctx, message.author.id):
        return True                                    # one in-character note per window, then silence
    await message.reply(answer.text, allowed_mentions=only_user(message.author))
    return True
