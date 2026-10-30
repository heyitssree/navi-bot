"""Settings that used to be hard-coded constants or could not be switched off now take effect at use time."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from navi.cogs.economy import EconomyCog
from navi.cogs.market import MarketGroup
from navi.cogs.shop import ShopGroup
from navi.db.connection import init_db
from navi.db.repos.users import upsert_user
from navi.handlers import pipeline
from navi.handlers.slang_points import handle_slang_points
from navi.handlers.vibe import handle_vibe
from navi.services.points import award
from navi.services.quota import check_cosmic_quota
from tests.legacy.harness import FakeLLM, FakeUser, make_ctx, make_message, points, seed


def interaction(ctx, user=None):
    i = MagicMock()
    i.client = ctx.bot
    i.user = user or FakeUser(1, "asha")
    i.response.send_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.is_done = lambda: False
    i.followup.send = AsyncMock()
    i.guild = None
    return i


async def test_market_and_shop_groups_respect_their_feature_switches(db):
    ctx = make_ctx(db)
    for group, key in ((MarketGroup(), "feature.market"), (ShopGroup(), "feature.shop")):
        i = interaction(ctx)
        assert await group.interaction_check(i) is True
        ctx.settings.set(key, False)
        i = interaction(ctx)
        assert await group.interaction_check(i) is False
        assert "switched off" in i.response.send_message.await_args.args[0]


async def test_gift_and_lucky_draw_switches_and_gift_daily_limit(db):
    ctx = make_ctx(db)
    seed(db, FakeUser(1, "asha"), FakeUser(2, "ben"))
    award(db, 1, 500, reason="seed")
    cog = EconomyCog(ctx)
    ben = SimpleNamespace(id=2, display_name="ben", bot=False, mention="<@2>")

    async def gift(amount):
        i = interaction(ctx)
        await cog.gift_slash.callback(cog, i, amount, ben)
        return i

    ctx.settings.set("feature.gift", False)
    assert "switched off" in (await gift(10)).response.send_message.await_args.args[0] and points(db, 1) == 500
    ctx.settings.set("feature.gift", True)
    await gift(50)
    assert points(db, 1) == 450 and points(db, 2) == 50
    ctx.settings.set("limit.gift_daily", 100)
    await gift(40)                                            # 90 of 100 today
    i = await gift(20)                                        # would be 110
    assert "Gift limit reached" in i.response.send_message.await_args.args[0] and points(db, 1) == 410
    ctx.settings.set("limit.gift_daily", 0)                   # 0 = no limit
    await gift(20)
    assert points(db, 1) == 390
    ctx.settings.set("feature.lucky_draw", False)
    i = interaction(ctx)
    await cog.lucky_draw_slash.callback(cog, i)
    assert "switched off" in i.response.send_message.await_args.args[0]


async def test_mention_qa_can_be_switched_off(db):
    llm = FakeLLM()
    ctx = make_ctx(db, llm=llm)
    ctx.bot.user.mentioned_in = lambda m: True
    seed(db, FakeUser(1, "asha"))
    msg = make_message(FakeUser(1, "asha"), "<@999> what is chaya?")
    ctx.settings.set("feature.mention_qa", False)
    await pipeline.on_message(ctx, msg)
    assert llm.requests == [] and msg.reply.await_count == 0
    ctx.settings.set("feature.mention_qa", True)
    msg = make_message(FakeUser(1, "asha"), "<@999> what is chaya?")
    await pipeline.on_message(ctx, msg)
    assert len(llm.requests) == 1 and llm.requests[0]["req"].purpose == "qa"
    assert msg.reply.await_args.args[0] == "LLM says hi"


async def test_daily_cosmic_action_quota_follows_the_setting(db):
    ctx = make_ctx(db)
    seed(db, FakeUser(1, "asha"))
    from navi.db.repos.counters import increment_daily_action_count

    for _ in range(3):
        increment_daily_action_count(db, 1)
    msg = make_message(FakeUser(1, "asha"), "navi")
    assert await check_cosmic_quota(ctx, msg.author, msg, "curse") is False             # 3 of 20
    ctx.settings.set("limit.daily_cosmic_actions", 3)
    assert await check_cosmic_quota(ctx, msg.author, msg, "curse") is True              # 3 of 3
    assert "/shop buy" in msg.reply.await_args.args[0]


async def test_slang_spam_thresholds_follow_the_settings(db):
    ctx = make_ctx(db)
    seed(db, FakeUser(1, "asha"))
    ctx.settings.override("feature.boli_points", True)

    async def send(text):
        await handle_slang_points(ctx, make_message(FakeUser(1, "asha"), text))
        return points(db, 1)

    assert await send("chumma") == 5 and await send("chumma") == 10          # first two short repeats still count
    assert await send("chumma") == 10                                         # third within the window: suppressed
    ctx2 = make_ctx(db)
    ctx2.settings.set("slang.spam_threshold", 10)
    seed(db, FakeUser(2, "ben"))
    for expected in (15, 20, 25, 30):
        await handle_slang_points(ctx2, make_message(FakeUser(2, "ben"), "chumma"))
        assert points(db, 2) == expected - 10


async def test_vibe_check_uses_window_and_threshold_settings(db):
    llm = FakeLLM(text="calm down")
    ctx = make_ctx(db, llm=llm)
    ctx.settings.set("vibe.min_messages", 3)
    ctx.settings.set("vibe.heated_ratio", 0.5)
    user = FakeUser(1, "asha")
    msgs = [make_message(user, "STOP SHOUTING NOW") for _ in range(3)]
    for m in msgs:
        await handle_vibe(ctx, m)
    assert msgs[-1].channel.send.await_count == 1 and msgs[-1].channel.send.await_args.args[0] == "calm down"
    ctx2 = make_ctx(db, llm=FakeLLM())
    quiet = [make_message(user, "STOP SHOUTING NOW") for _ in range(3)]
    for m in quiet:
        await handle_vibe(ctx2, m)                        # default min_messages is 10: nothing yet
    assert quiet[-1].channel.send.await_count == 0


async def test_strike_escalation_prefers_the_configured_mod_channel(db):
    from navi.db.repos.users import get_user_strikes
    from navi.handlers.strikes import handle_strike

    ctx = make_ctx(db, mod_channel_name="mod-log")
    seed(db, FakeUser(1, "asha"))
    db.execute("UPDATE users SET strikes = 2 WHERE user_id = 1"); db.commit()
    member = SimpleNamespace(id=1, display_name="asha", mention="<@1>")
    configured, named = AsyncMock(), AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    channel.guild = SimpleNamespace(get_channel=lambda cid: configured if cid == 99 else None,
                                    text_channels=[SimpleNamespace(name="mod-log", send=named.send)])
    ctx.settings.set("channel.mod_alerts", 99)
    await handle_strike(ctx, member, channel)
    assert configured.send.await_count == 1 and named.send.await_count == 0 and get_user_strikes(db, 1) == 0


def test_phase_3_settings_keys_are_renamed_by_migration_0002(tmp_path):
    from navi.db.migrate import current_version, migrate

    path = tmp_path / "p3.db"
    conn = init_db(path)
    conn.execute("DELETE FROM schema_version WHERE version = 2")
    conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", [
        ("feature.curse_replies", "false"), ("feature.link_summary_emoji", '"X"'),
        ("limit.local_media_max_per_user", "5"), ("limit.local_media_max_global", "9"), ("chance.kochi_reply", "0.5")])
    conn.commit()
    assert migrate(conn) == 2 == current_version(conn)
    assert dict(conn.execute("SELECT key, value FROM settings")) == {
        "feature.passive_curse_replies": "false", "emoji.link_summary": '"X"', "limit.media_per_user": "5",
        "limit.media_global": "9", "chance.kochi_reply": "0.5"}
