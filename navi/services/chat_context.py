# navi/services/chat_context.py - the last few channel messages, as context for a question (privacy-filtered)
#
# Same protections as the reply-chain context: opted-out people and every bot except Navi are left out, mentions and links to people are scrubbed,
# every line (and every name) goes through the safety filter, and the total is capped. Chat lines are untrusted text: the prompt tells the model
# to treat them as quotes, never as instructions. Needs `ai.channel_context_messages` > 0 (default 20).
from __future__ import annotations

import logging
import re

import discord

from navi.llm import safety

logger = logging.getLogger("navi.services.chat_context")

LINE_CHARS = 300
TOTAL_CHARS = 3000
_MENTION = re.compile(r"<@[!&]?\d+>|<#\d+>|@everyone|@here")


async def build(ctx, message: discord.Message) -> list[tuple[str, str]]:
    """[(speaker, text)] for the messages just before `message`, oldest first. Empty on any failure or when switched off."""
    limit = int(ctx.settings.get("ai.channel_context_messages"))
    if limit <= 0:
        return []
    out: list[tuple[str, str]] = []
    chars = 0
    try:
        async for m in message.channel.history(limit=limit, before=message):
            is_navi = m.author.id == ctx.bot.user.id
            if (m.author.bot and not is_navi) or ctx.privacy.is_opted_out(m.author.id):
                continue
            text = _MENTION.sub("", m.content or "").strip()[:LINE_CHARS]
            name = "Navi" if is_navi else m.author.display_name
            if not text or not safety.check_input(text).ok:
                continue
            if not safety.check_input(name).ok:
                name = "Someone"
            if chars + len(text) > TOTAL_CHARS:
                break
            chars += len(text)
            out.append((name, text))
    except (discord.HTTPException, AttributeError, TypeError):
        logger.warning("Could not read channel history for context.")
        return []
    out.reverse()
    return out
