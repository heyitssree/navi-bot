"""navi/handlers/pipeline.py - the on_message chain.

Each handler is `async def handler(ctx, message) -> bool` and returns True when it consumed the message
(processing stops). The ORDER below is exactly the order of the old monolithic on_message and must be kept:

  guards (inline)  db not ready / master killswitch / bots / replies to Navi -> ignore
   1. track_user     last_seen + first-message-per-session upsert                  never consumes
   2. shortcuts      ";;name" local media shortcut                                 consumes when it matched
   3. vibe           channel heat tracker                                          never consumes
   4. slang_points   Boli for slang triggers + slang dictionary (spam gated)       never consumes
   5. kochi          Kochi slang -> condescending reply (chance)                   consumes when it fires
   6. mention_qa     @Navi question -> LLM answer                                  consumes on any mention
   7. curse command  "navi", "navi @user", reply "navi"                            consumes
   8. bless command  "chunk", "chunk @user", reply "chunk"                         consumes
   9. passive_curse  curse word in any message -> +1 Boli, LLM line (chance)       never consumes

Later phases insert the privacy gate (before 1, after the guards) and the #bot-commands context reply (before 7).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from navi.db.repos.users import upsert_user
from navi.handlers.curse_commands import handle_chunk_command, handle_navi_command
from navi.handlers.kochi import handle_kochi
from navi.handlers.mention_qa import handle_mention_qa
from navi.handlers.passive_curse import handle_passive_curse
from navi.handlers.shortcuts import handle_shortcut
from navi.handlers.slang_points import handle_slang_points
from navi.handlers.vibe import handle_vibe

logger = logging.getLogger("navi.handlers.pipeline")


async def track_user(ctx, message: discord.Message) -> bool:
    """Record last_seen in memory on every message; upsert the user on their first message per session."""
    ctx.state.last_seen_pending[message.author.id] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Upsert user record only on first message per session (in-memory cache to avoid DB write on every message)
    if message.author.id not in ctx.state.seen_users:
        upsert_user(ctx.db, message.author.id, message.author.display_name)
        ctx.state.seen_users.add(message.author.id)
    return False


HANDLERS = [
    track_user,
    handle_shortcut,
    handle_vibe,
    handle_slang_points,
    handle_kochi,
    handle_mention_qa,
    handle_navi_command,
    handle_chunk_command,
    handle_passive_curse,
]


async def on_message(ctx, message: discord.Message) -> None:
    # Guard against messages arriving before on_ready finishes initialising
    if ctx.db is None:
        return

    # Master kill switch - ignore everything (except owner text commands)
    if ctx.settings.get("system.killswitch"):
        return

    # Ignore other bots
    if message.author.bot:
        return

    # Ignore replies to bot's own messages
    if message.reference:
        resolved = message.reference.resolved or message.reference.cached_message
        if isinstance(resolved, discord.Message) and resolved.author.id == ctx.bot.user.id:
            return

    for handler in HANDLERS:
        if await handler(ctx, message):
            return
