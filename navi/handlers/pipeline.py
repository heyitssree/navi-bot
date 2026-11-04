"""navi/handlers/pipeline.py - the on_message chain.

Each handler is `async def handler(ctx, message) -> bool` and returns True when it consumed the message
(processing stops). The ORDER below is exactly the order of the old monolithic on_message and must be kept:

  guards (inline)  db not ready / master killswitch -> ignore
                   opted-out author (privacy) -> drop: no points, logging, replies or counters
                   bots -> ignored, except Ammavan (services/ammavan.py: rare curse-back / witty remark); replies to Navi -> ignore unless they tag Navi (<@id> in the text)
   1. track_user     last_seen + first-message-per-session upsert                  never consumes
      track_ammavan  remembers "." / "ammava..." texts per channel (Ammavan bot)    never consumes
      track_emojis   copies foreign custom emojis into Navi's emoji inventory (FIFO) never consumes
   2. shortcuts      ";;name" local media shortcut                                 consumes when it matched
   3. vibe           channel heat tracker                                          never consumes
   4. slang_points   Boli for slang triggers + slang dictionary (spam gated)       never consumes
   5. kochi          Kochi slang -> condescending reply (chance)                   consumes when it fires
   6. context_reply  reply chain / mention in the bot-commands channel             consumes when it applies
   7. mention_qa     @Navi question -> knowledge / cache / LLM answer              consumes on any mention
   8. curse command  "navi", "navi @user", reply "navi"                            consumes
   9. bless command  "chunk", "chunk @user", reply "chunk"                         consumes
  10. passive_curse  curse word in any message -> +1 Boli, reviewed template       never consumes
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from navi.db.repos.users import upsert_user
from navi.services import emojis
from navi.handlers.context_reply import handle_context_reply
from navi.handlers.curse_commands import handle_chunk_command, handle_navi_command
from navi.handlers.kochi import handle_kochi
from navi.handlers.mention_qa import handle_mention_qa
from navi.handlers.passive_curse import handle_passive_curse
from navi.handlers.shortcuts import handle_shortcut
from navi.handlers.slang_points import handle_slang_points
from navi.handlers.vibe import handle_vibe
from navi.services import ammavan

logger = logging.getLogger("navi.handlers.pipeline")


async def track_user(ctx, message: discord.Message) -> bool:
    """Record last_seen in memory on every message; upsert the user on their first message per session."""
    ctx.state.last_seen_pending[message.author.id] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Upsert user record only on first message per session (in-memory cache to avoid DB write on every message)
    if message.author.id not in ctx.state.seen_users:
        upsert_user(ctx.db, message.author.id, message.author.display_name)
        ctx.state.seen_users.add(message.author.id)
    return False


async def track_ammavan(ctx, message: discord.Message) -> bool:
    """Remember "." and "ammava..." texts so Ammavan's answers can be recognised (never consumes)."""
    ammavan.track_human(ctx, message)
    return False


async def track_emojis(ctx, message: discord.Message) -> bool:
    """Learn custom emojis seen in chat into Navi's emoji inventory (never consumes)."""
    await emojis.learn(ctx.bot, message)
    return False


HANDLERS = [
    track_user,
    track_ammavan,
    track_emojis,
    handle_shortcut,
    handle_vibe,
    handle_slang_points,
    handle_kochi,
    handle_context_reply,
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

    # Opted-out users: no points, logging, replies or counters - the message is dropped entirely
    if ctx.privacy.is_opted_out(message.author.id):
        return

    # Ignore other bots. The one exception is the Ammavan bot (ammavan.bot_ids), which Navi may rarely answer; nothing else ever reacts to a bot.
    if message.author.bot:
        try:
            await ammavan.handle_ammavan(ctx, message)
        except Exception:
            logger.exception("Ammavan reaction failed")
        return

    # A reply to one of Navi's messages is ignored unless it explicitly tags Navi. (A reply's automatic ping does not count:
    # only a literal <@id> in the text does.)
    if message.reference:
        resolved = message.reference.resolved or message.reference.cached_message
        if isinstance(resolved, discord.Message) and resolved.author.id == ctx.bot.user.id:
            if f"<@{ctx.bot.user.id}>" not in message.content and f"<@!{ctx.bot.user.id}>" not in message.content:
                return

    for handler in HANDLERS:
        try:
            if await handler(ctx, message):
                return
        except discord.Forbidden:                     # e.g. a mention in a channel Navi cannot see or write to: nothing to do
            logger.warning("Missing access in channel %s; skipped %s.", getattr(message.channel, "id", "?"), handler.__name__)
            return
