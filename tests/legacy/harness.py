"""Helpers that drive the pipeline / cogs with fake Discord objects against a temp DB."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from navi.config import Config
from navi.context import AppContext
from navi.services.privacy import Privacy
from navi.settings.store import Settings

BOT_ID = 999


class FakeUser:
    def __init__(self, uid, name=None, is_bot=False):
        self.id = uid
        self.display_name = name or f"user{uid}"
        self.bot = is_bot
        self.mention = f"<@{uid}>"

    def __str__(self):
        return self.display_name


def make_message(author, content, mentions=(), reference_author=None):
    msg = MagicMock(spec=discord.Message)
    msg.author = author
    msg.content = content
    msg.mentions = list(mentions)
    msg.guild = SimpleNamespace(id=1)
    msg.channel = MagicMock()
    msg.channel.id = 10
    msg.channel.send = AsyncMock()
    msg.reply = AsyncMock()
    if reference_author is not None:
        resolved = MagicMock(spec=discord.Message)
        resolved.author = reference_author
        msg.reference = SimpleNamespace(resolved=resolved, cached_message=None)
    else:
        msg.reference = None
    return msg


def make_config(**kw):
    base = dict(discord_token=None, free_api_key=None, paid_api_key=None, llm_model=None, free_tier_mode=True,
                general_channel="general", mod_channel_name="mod-log", owner_id=None, guild_id=None, partner_port=8080)
    base.update(kw)
    return Config(**base)


def make_ctx(db, llm=None, **cfg):
    """An AppContext wired to a temp DB and a fake Discord client (user id BOT_ID)."""
    bot = SimpleNamespace(
        user=SimpleNamespace(id=BOT_ID, mentioned_in=lambda m: False),
        application_info=AsyncMock(),
    )
    ctx = AppContext(bot=bot, config=make_config(**cfg), settings=Settings(), privacy=Privacy())
    ctx.db = db
    ctx.settings.bind(db)
    ctx.llm = llm
    bot.ctx = ctx
    return ctx


def seed(db, *users):
    from navi.db.repos.users import upsert_user

    for u in users:
        upsert_user(db, u.id, u.display_name)


def points(db, uid):
    return db.execute("SELECT boli_points FROM users WHERE user_id=?", [uid]).fetchone()[0]


def xp(db, uid):
    return db.execute("SELECT experience FROM users WHERE user_id=?", [uid]).fetchone()[0]


class FakeLLM:
    """Stands in for LLMRouter: records requests, returns canned text."""

    free_only = False

    def __init__(self, text="LLM says hi", from_cache=False, pool="POOL"):
        self.requests, self.cache_only_calls = [], []
        self.text, self.from_cache, self.pool = text, from_cache, pool

    async def generate(self, req, *, fallback, name="", cache_type=None, curse_used=None, user_id=None, cacheable=None):
        from navi.llm.router import RouterResult

        self.requests.append(dict(req=req, fallback=fallback, name=name, cache_type=cache_type, curse_used=curse_used))
        return RouterResult(self.text, self.from_cache, "ok")

    async def cache_only(self, cache_type, name, fallback, curse_used=None):
        from navi.llm.router import RouterResult

        self.cache_only_calls.append(dict(cache_type=cache_type, name=name))
        return RouterResult(self.pool, True, "cache")
