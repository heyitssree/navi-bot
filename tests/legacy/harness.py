"""Helpers that drive bot.on_message with fake Discord objects against a temp DB."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

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


def install(navi, monkeypatch, db):
    """Point the bot module at the temp DB with a fake client user."""
    fake_client = SimpleNamespace(user=SimpleNamespace(id=BOT_ID, mentioned_in=lambda m: False))
    monkeypatch.setattr(navi, "bot", fake_client)
    monkeypatch.setattr(navi, "db_conn", db)
    monkeypatch.setattr(navi, "_seen_users", set())
    monkeypatch.setattr(navi, "_feature_cache", dict(navi._FEATURE_DEFAULTS))


def seed(db, schema, *users):
    for u in users:
        schema.upsert_user(db, u.id, u.display_name)


def points(db, uid):
    return db.execute("SELECT boli_points FROM user_stats WHERE user_id=?", [uid]).fetchone()[0]


def xp(db, uid):
    return db.execute("SELECT experience FROM user_stats WHERE user_id=?", [uid]).fetchone()[0]
