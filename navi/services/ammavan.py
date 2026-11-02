# navi/services/ammavan.py - light-touch reactions to another bot, Ammavan (proxy-curse and AI-chat bot)
#
# Ammavan curses on someone's behalf when a text starts with "." (it swaps the dot for a curse and posts the whole text), and chats with AI
# when a text starts with the lower-case string "ammava". Navi only ever does two things, each rare and per-channel rate-limited:
#   * when Ammavan proxy-curses: curse Ammavan back with a reviewed template (chance.ammavan_curse_back, default 5%)
#   * when Ammavan answers an AI chat: a short playful reply in English (chance.ammavan_witty_reply, default 30%)
# Everything else Ammavan does is ignored. Every other bot is ignored as before: the pipeline drops bot messages, and only the IDs in
# ammavan.bot_ids reach this module. Navi never replies in a way that could trigger Ammavan (no leading "." or "ammava"), never answers a
# message that is itself a reply to Navi (no bot-to-bot loops), and never reacts when an opted-out user is involved.
from __future__ import annotations

import logging
import random
import re
import time

from navi.data.curse_data import contains_curse_word, get_random_doomed_prediction
from navi.llm import safety
from navi.llm.base import LLMRequest
from navi.llm.prompts import get_ammavan_witty_prompt, get_time_aware_system_prompt
from navi.services.mentions import nobody
from navi.services.template_pool import pick

logger = logging.getLogger("navi.services.ammavan")

CURSE_WINDOW = 15.0          # seconds between a person's "." text and Ammavan's curse
AI_WINDOW = 30.0             # seconds between a person's "ammava ..." text and Ammavan's answer
AI_PREFIX = "ammava"
SAFE_PREFIX = "✨ "
_MENTION = re.compile(r"<@[!&]?\d+>|<#\d+>|@everyone|@here")


def ammavan_ids(ctx) -> set[int]:
    return {int(i) for i in (ctx.settings.get("ammavan.bot_ids") or [])}


def is_ammavan(ctx, user) -> bool:
    return bool(user is not None and ctx.settings.get("feature.ammavan_reactions") and user.id in ammavan_ids(ctx))


def bot_safe(text: str) -> str:
    """Never start a message with "." or "ammava": that is what Ammavan reacts to."""
    text = text.strip()
    while text.startswith("."):
        text = text[1:].lstrip()
    return SAFE_PREFIX + text if text.lower().startswith(AI_PREFIX) else text


def track_human(ctx, message, now: float | None = None) -> None:
    """Remember the latest "." and "ammava..." texts per channel so Ammavan's answer can be recognised. Never consumes."""
    if not ammavan_ids(ctx) or not ctx.settings.get("feature.ammavan_reactions"):
        return
    now = time.monotonic() if now is None else now
    content = message.content or ""
    if content.startswith("."):
        ctx.state.ammavan_dot[message.channel.id] = (message.author.id, content[1:].strip(), now)
    elif content.startswith(AI_PREFIX):
        ctx.state.ammavan_ai[message.channel.id] = (message.id, message.author.id, now, _MENTION.sub("", content[len(AI_PREFIX):]).strip()[:200])


def classify(ctx, message, now: float) -> tuple[str | None, int | None]:
    """('curse' | 'ai' | None, the person who triggered it). Ammavan messages that match neither are other interactions: left alone."""
    channel = message.channel.id
    content = (message.content or "").lower()
    dot = ctx.state.ammavan_dot.get(channel)
    if dot and now - dot[2] <= CURSE_WINDOW and (not dot[1] or dot[1].lower() in content):
        return "curse", dot[0]
    ai = ctx.state.ammavan_ai.get(channel)
    if ai and now - ai[2] <= AI_WINDOW:
        ref = getattr(message.reference, "message_id", None) if message.reference else None
        if ref is None or ref == ai[0]:
            return "ai", ai[1]
    return None, None


def _replies_to_navi(ctx, message) -> bool:
    ref = message.reference
    parent = (getattr(ref, "resolved", None) or getattr(ref, "cached_message", None)) if ref else None
    return bool(parent is not None and getattr(getattr(parent, "author", None), "id", None) == ctx.bot.user.id)


def _opted_out_involved(ctx, message, trigger_id: int | None) -> bool:
    ids = [trigger_id] if trigger_id else []
    ids += [int(m) for m in re.findall(r"<@!?(\d+)>", message.content or "")]
    ids += [u.id for u in getattr(message, "mentions", []) or []]
    return any(ctx.privacy.is_opted_out(i) for i in ids)


async def handle_ammavan(ctx, message, *, rand=None, now: float | None = None) -> bool:
    """React (rarely) to one message from Ammavan. Returns True when Navi replied."""
    if not is_ammavan(ctx, message.author) or _replies_to_navi(ctx, message):
        return False
    now = time.monotonic() if now is None else now
    channel = message.channel.id
    if now - ctx.state.ammavan_last.get(channel, -1e12) < ctx.settings.get("limit.ammavan_cooldown_seconds"):
        return False
    kind, trigger = classify(ctx, message, now)
    if kind is None or _opted_out_involved(ctx, message, trigger):
        return False
    chance = ctx.settings.get("chance.ammavan_curse_back" if kind == "curse" else "chance.ammavan_witty_reply")
    if (rand or random.random)() >= chance:
        return False
    text = curse_back_text(ctx, message) if kind == "curse" else await witty_text(ctx, message)
    if not text:
        return False
    text = bot_safe(text)
    ctx.state.ammavan_last[channel] = now
    await message.reply(text, allowed_mentions=nobody())
    logger.info("Ammavan %s: replied (%d chars).", kind, len(text))
    return True


def curse_back_text(ctx, message) -> str | None:
    matched, word = contains_curse_word(message.content or "")
    name = message.author.display_name
    return pick(ctx, "curse_back", message.author.id, name, word if matched else None) or get_random_doomed_prediction(name)


async def witty_text(ctx, message) -> str | None:
    said = _MENTION.sub("", message.content or "").strip()[:300]
    if not said or not safety.check_input(said).ok:
        return None
    trigger = ctx.state.ammavan_ai.get(message.channel.id)
    asked = trigger[3] if trigger and safety.check_input(trigger[3]).ok else ""
    res = await ctx.llm.generate(
        LLMRequest(purpose="qa", system=get_time_aware_system_prompt(ctx.db, username=None), prompt=get_ammavan_witty_prompt(said, asked), max_tokens=90),
        fallback="", name="Ammavan", cache_type="ammavan",
    )
    return res.text.strip() if res.outcome == "ok" and not res.from_cache and res.text.strip() else None
