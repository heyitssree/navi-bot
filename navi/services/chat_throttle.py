# navi/services/chat_throttle.py - keep AI conversation out of the general channels (mention Q&A only)
#
# Outside the bot-commands channel a person may talk to Navi `chat.redirect_calls` times per `chat.redirect_window_seconds` (default 4 in 5 minutes).
# The next attempt gets ONE in-character note pointing at the bot-commands channel, and Navi then ignores that person's AI conversation for
# `chat.redirect_cooldown_seconds` (default 5 minutes). In the bot-commands channel there is no limit. Only AI conversation is affected: commands,
# games, shortcuts and every other feature work as before. Needs channel.bot_commands to be set; without it there is nowhere to send people, so nothing is throttled.
from __future__ import annotations

import random
import time
from collections import deque

ALLOW, REDIRECT, SILENT = "allow", "redirect", "silent"

REDIRECT_MESSAGES: list[str] = [
    "🌌 {user}, we're chatting a lot. Take this to {channel}, where I talk freely. I'll sit this one out here for about {minutes} minutes.",
    "✨ {user}, the stars say this conversation belongs in {channel}. Meet me there. I'm quiet here for the next {minutes} minutes.",
    "🔮 Easy, {user}. Long chats go in {channel} so the other channels can breathe. I'll be silent here for {minutes} minutes.",
    "🌠 {user}, let's move this to {channel}. I answer there anytime, and I'll pause here for {minutes} minutes.",
]


def free_channel_id(ctx) -> int | None:
    return ctx.settings.get("channel.bot_commands") or None


def check(ctx, user_id: int, channel_id: int, now: float | None = None) -> str:
    """Decide what to do with one AI-conversation attempt: ALLOW it, send the REDIRECT note (once), or stay SILENT."""
    s = ctx.settings
    free = free_channel_id(ctx)
    if not s.get("feature.chat_redirect") or not free or channel_id == free:
        return ALLOW
    now = time.monotonic() if now is None else now
    state = ctx.state
    until = state.chat_cooldown.get(user_id)
    if until is not None:
        if now < until:
            return SILENT
        del state.chat_cooldown[user_id]
    calls = state.chat_calls.setdefault(user_id, deque())
    window = float(s.get("chat.redirect_window_seconds"))
    while calls and now - calls[0] >= window:
        calls.popleft()
    if len(calls) >= int(s.get("chat.redirect_calls")):
        calls.clear()
        state.chat_cooldown[user_id] = now + float(s.get("chat.redirect_cooldown_seconds"))
        return REDIRECT
    calls.append(now)
    return ALLOW


def redirect_text(ctx, user) -> str:
    minutes = max(1, round(float(ctx.settings.get("chat.redirect_cooldown_seconds")) / 60))
    return random.choice(REDIRECT_MESSAGES).format(user=user.display_name, channel=f"<#{free_channel_id(ctx)}>", minutes=minutes)
