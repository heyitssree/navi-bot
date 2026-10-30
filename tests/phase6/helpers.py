from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord


def interaction(ctx, user=None, guild_id=500, channel=None):
    i = MagicMock()
    i.client = ctx.bot
    i.user = user or SimpleNamespace(id=1, display_name="asha", roles=[], guild_permissions=SimpleNamespace(manage_messages=False))
    i.guild_id = guild_id
    i.guild = None
    i.channel = channel
    i.command = None
    i.response.send_message = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.is_done = lambda: False
    i.edit_original_response = AsyncMock()
    i.original_response = AsyncMock()
    i.followup.send = AsyncMock()
    return i


def said(i) -> str:
    args, kwargs = i.response.send_message.await_args
    return args[0] if args else kwargs.get("content", "")


def member(uid, name=None, manage_messages=False, bot=False):
    return SimpleNamespace(id=uid, display_name=name or f"user{uid}", mention=f"<@{uid}>", bot=bot, roles=[],
                           guild_permissions=SimpleNamespace(manage_messages=manage_messages))


def reply_msg(author, content, to=None, channel_id=10, mentions_bot=False, ctx_bot=None):
    """A fake discord.Message. `to` is the parent message (a fake from this helper) it replies to."""
    from tests.legacy.harness import make_message

    msg = make_message(author, content)
    msg.channel.id = channel_id
    msg.id = id(msg) % 10**9
    if to is not None:
        msg.reference = SimpleNamespace(resolved=to, cached_message=None, message_id=to.id)
    if mentions_bot:
        msg.content = f"<@999> {content}"
    return msg
