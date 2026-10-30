"""/privacy: purge, enforcement at every point, opt-in cooldown."""
import os
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from navi.app import build
from navi.cogs.economy import EconomyCog
from navi.cogs.moderation import ModerationCog
from navi.cogs.predictions import PredictionsCog
from navi.cogs.privacy import OptOutView, PrivacyGroup
from navi.cogs.summaries import SummariesCog
from navi.db.repos.counters import increment_daily_action_count
from navi.db.repos.privacy import connect_privacy, get_state, set_status
from navi.db.repos.users import get_user_profile, upsert_user
from navi.handlers import pipeline
from navi.handlers.curse_commands import handle_chunk_command, handle_navi_command
from navi.services.points import award
from navi.services.privacy import OPTED_OUT_MESSAGE, Privacy, purge_user
from tests.legacy.harness import FakeLLM, FakeUser, make_config, make_ctx, make_message, points
from tests.phase6.helpers import interaction, member, said

ME, OTHER = 77, 88


def populate(db, tmp_path):
    """User 77 gets a row in every user-linked table; user 88 references them everywhere."""
    for uid in (ME, OTHER):
        upsert_user(db, uid, f"user{uid}")
    award(db, ME, 50, 10, reason="slang", counterparty_id=OTHER)
    award(db, OTHER, 5, reason="gift_received", counterparty_id=ME)
    db.execute("INSERT INTO daily_counters VALUES (?, date('now'), 'cosmic_action', 3)", [ME])
    db.execute("INSERT INTO market_items (item_id, name, emoji, base_price, current_price) VALUES ('x', 'X', 'e', 1, 1)")
    db.execute("INSERT INTO holdings (user_id, item_id, quantity, purchase_price, expires_at) VALUES (?, 'x', 1, 1, datetime('now', '+1 day'))", [ME])
    db.execute("INSERT INTO perks VALUES (?, 'curse_protection', datetime('now', '+1 day'))", [ME])
    local = tmp_path / "me.png"
    local.write_bytes(b"png")
    db.execute("INSERT INTO media (shortcut, owner_id, storage_type, location) VALUES ('mine', ?, 'local', ?)", [ME, str(local)])
    db.execute("INSERT INTO media (shortcut, owner_id, storage_type, location, discord_id) VALUES ('solo', ?, 'app_emoji', '', '111')", [ME])
    db.execute("INSERT INTO media (shortcut, owner_id, storage_type, location, discord_id) VALUES ('shared1', ?, 'app_emoji', '', '222')", [ME])
    db.execute("INSERT INTO media (shortcut, owner_id, storage_type, location, discord_id) VALUES ('shared2', ?, 'app_emoji', '', '222')", [OTHER])
    db.executemany("INSERT INTO app_emojis (emoji_id, name) VALUES (?, 'e')", [("111",), ("222",)])
    db.execute("INSERT INTO game_results (game, user_id, game_id, score) VALUES ('fff', ?, 'g1', 5)", [ME])
    db.execute("INSERT INTO prediction_history (user_id, text) VALUES (?, 'p')", [ME])
    db.execute("INSERT INTO events (kind, user_id, name) VALUES ('command', ?, 'navi')", [ME])
    db.execute("INSERT INTO permissions (user_id, permission, granted_by) VALUES (?, 'teach', ?)", [ME, OTHER])
    db.execute("INSERT INTO permissions (user_id, permission, granted_by) VALUES (?, 'teach', ?)", [OTHER, ME])
    db.execute("INSERT INTO knowledge (category, term, description, submitted_by, approved_by) VALUES ('food', 'Pori', 'banana fritter ok', ?, ?)", [ME, ME])
    db.execute("INSERT INTO content (kind, text, status, source, reviewed_by) VALUES ('curse_back', 'hi {user}', 'active', 'llm', ?)", [ME])
    db.execute("INSERT INTO settings (key, value, updated_by) VALUES ('ai.rpm_budget', '20', ?)", [ME])
    db.commit()
    return local


def user_columns(db):
    cols = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        for c in db.execute(f'PRAGMA table_info("{table}")'):
            if c[1] in ("user_id", "owner_id", "counterparty_id", "submitted_by", "approved_by", "reviewed_by", "updated_by", "granted_by"):
                cols.append((table, c[1]))
    return cols


def test_opt_out_leaves_no_trace_in_any_user_linked_table(db, tmp_path):
    local = populate(db, tmp_path)
    ctx = make_ctx(db)
    ctx.state.seen_users.add(ME); ctx.state.last_seen_pending[ME] = "x"; ctx.state.user_level_cache[ME] = 3
    result = ctx.privacy.opt_out(ctx, ME)
    leftovers = {(t, c): n for t, c in user_columns(db) if (n := db.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}" = ?', [ME]).fetchone()[0])}
    assert leftovers == {}, leftovers                                   # every table, every user-reference column
    assert not os.path.exists(local)                                    # the user's file is gone
    assert result.orphan_app_emojis == ["111"]                          # emoji only they used; "222" is shared
    assert db.execute("SELECT emoji_id FROM app_emojis").fetchall()[0][0] == "222"
    assert not ctx.state.seen_users and not ctx.state.last_seen_pending and not ctx.state.user_level_cache
    ev = db.execute("SELECT kind, name, user_id FROM events WHERE kind='privacy'").fetchone()
    assert tuple(ev) == ("privacy", "opt_out", None)                    # a count only


def test_other_users_data_survives_with_references_cleared(db, tmp_path):
    populate(db, tmp_path)
    ctx = make_ctx(db)
    ctx.privacy.opt_out(ctx, ME)
    assert get_user_profile(db, OTHER)["boli_points"] == 5
    assert db.execute("SELECT counterparty_id FROM points_ledger WHERE user_id=?", [OTHER]).fetchone()[0] is None
    assert db.execute("SELECT submitted_by, approved_by FROM knowledge").fetchone()[:] == (None, None)
    assert db.execute("SELECT reviewed_by FROM content").fetchone()[0] is None
    assert db.execute("SELECT updated_by FROM settings").fetchone()[0] is None
    assert db.execute("SELECT granted_by FROM permissions WHERE user_id=?", [OTHER]).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM media WHERE owner_id=?", [OTHER]).fetchone()[0] == 1
    for uid in (OTHER,):                                                 # ledgers still reconcile
        assert db.execute("SELECT SUM(delta) FROM points_ledger WHERE user_id=?", [uid]).fetchone()[0] == points(db, uid)


def test_purge_is_one_transaction(db, tmp_path):
    populate(db, tmp_path)
    db.execute("CREATE TRIGGER boom BEFORE DELETE ON perks BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(Exception, match="boom"):
        purge_user(db, ME)
    assert get_user_profile(db, ME) is not None                          # nothing was deleted
    assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE user_id=?", [ME]).fetchone()[0] == 1


def test_opt_out_is_recorded_before_the_purge_so_a_crash_still_blocks(db, tmp_path):
    populate(db, tmp_path)
    conn = connect_privacy(tmp_path / "privacy.db")
    ctx = make_ctx(db)
    ctx.privacy = Privacy(conn)
    db.execute("CREATE TRIGGER boom BEFORE DELETE ON users BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(Exception, match="boom"):
        ctx.privacy.opt_out(ctx, ME)
    assert ctx.privacy.is_opted_out(ME) and get_state(conn, ME)[0] == "out"
    assert Privacy(conn).is_opted_out(ME)                                # survives a restart (loaded from privacy.db)


def test_privacy_db_stores_only_id_status_and_time(tmp_path):
    conn = connect_privacy(tmp_path / "p.db")
    assert [c[1] for c in conn.execute("PRAGMA table_info(privacy_state)")] == ["user_id", "status", "changed_at"]


def test_opt_in_cooldown_and_fresh_profile(db, tmp_path):
    conn = connect_privacy(":memory:")
    privacy = Privacy(conn)
    ctx = make_ctx(db)
    ctx.privacy = privacy
    upsert_user(db, ME, "me"); award(db, ME, 99, reason="x")
    privacy.opt_out(ctx, ME)
    day = datetime(2026, 10, 30, tzinfo=timezone.utc)
    set_status(conn, ME, "out", day.strftime("%Y-%m-%d %H:%M:%S"))
    early = privacy.opt_in(ME, 7, now=day + timedelta(days=6, hours=23))
    assert not early.ok and early.available_on == "2026-11-06" and privacy.is_opted_out(ME)
    ok = privacy.opt_in(ME, 7, now=day + timedelta(days=7))
    assert ok.ok and not privacy.is_opted_out(ME)
    assert get_user_profile(db, ME) is None                              # nothing comes back; the next message creates a new profile
    upsert_user(db, ME, "me")
    assert get_user_profile(db, ME)["boli_points"] == 0
    assert privacy.opt_in(ME, 7).message == "You're already opted in."


# ------------------------------------------------------------------------------ enforcement

async def test_messages_from_opted_out_users_are_dropped_completely(db):
    llm = FakeLLM()
    ctx = make_ctx(db, llm=llm)
    ctx.privacy.mark_out(ME)
    user = FakeUser(ME, "me")
    for text in ("chumma kidilam", "you mandan", "navi", "chunk", "navi <@88>", ";;lol", "hello"):
        msg = make_message(user, text, mentions=[FakeUser(88)] if "<@" in text else [])
        await pipeline.on_message(ctx, msg)
        assert msg.reply.await_count == 0 and msg.channel.send.await_count == 0
    assert get_user_profile(db, ME) is None and not ctx.state.last_seen_pending and not ctx.state.seen_users
    assert db.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0 and llm.requests == []


async def test_slash_commands_are_refused_except_privacy(db):
    bot, ctx = build(make_config(owner_id=1))
    ctx.db = db
    ctx.privacy.mark_out(ME)
    tree = bot.tree
    for name, allowed in (("rank", False), ("privacy opt_in", True), ("privacy status", True), ("admin panel", False)):
        i = interaction(ctx, user=member(ME))
        i.client = bot
        i.command = SimpleNamespace(qualified_name=name)
        assert await tree.interaction_check(i) is allowed, name
        if not allowed:
            assert said(i) == OPTED_OUT_MESSAGE
    owner = interaction(ctx, user=member(1)); owner.client = bot
    ctx.privacy.mark_out(1)
    owner.command = SimpleNamespace(qualified_name="admin panel")
    assert await tree.interaction_check(owner) is True                    # the owner keeps /admin
    stranger = interaction(ctx, user=member(5)); stranger.client = bot
    stranger.command = SimpleNamespace(qualified_name="rank")
    assert await tree.interaction_check(stranger) is True


@pytest.fixture()
def duel(db, monkeypatch):
    ctx = make_ctx(db, llm=FakeLLM())
    ctx.privacy.mark_out(OTHER)
    upsert_user(db, 1, "caster")
    monkeypatch.setattr(random, "random", lambda: 0.99)
    return ctx


async def test_curses_and_blessings_refuse_opted_out_targets_without_using_quota(duel):
    ctx = duel
    caster, target = FakeUser(1, "caster"), FakeUser(OTHER, "gone")
    cases = [
        (handle_navi_command, make_message(caster, f"navi <@{OTHER}>", mentions=[target])),
        (handle_navi_command, make_message(caster, "navi", reference_author=target)),
        (handle_chunk_command, make_message(caster, f"chunk <@{OTHER}>", mentions=[target])),
        (handle_chunk_command, make_message(caster, "chunk", reference_author=target)),
    ]
    for handler, msg in cases:
        assert await handler(ctx, msg) is True
        assert "opted out" in msg.reply.await_args.args[0]
    assert ctx.db.execute("SELECT COUNT(*) FROM daily_counters").fetchone()[0] == 0     # quota untouched
    assert ctx.db.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0 and get_user_profile(ctx.db, OTHER) is None


async def test_gift_refuses_opted_out_recipient_and_random_picker_skips_them(db):
    ctx = make_ctx(db)
    ctx.privacy.mark_out(OTHER)
    upsert_user(db, 1, "asha"); upsert_user(db, OTHER, "gone"); upsert_user(db, 5, "ben")
    award(db, 1, 100, reason="seed")
    db.execute("INSERT INTO prediction_history (user_id, text) VALUES (?, 'p'), (?, 'p')", [OTHER, 5]); db.commit()
    cog = EconomyCog(ctx)
    i = interaction(ctx, user=member(1))
    await cog.gift_slash.callback(cog, i, 10, member(OTHER, "gone"))
    assert "opted out" in said(i) and points(db, 1) == 100
    from navi.db.repos.users import get_random_recent_user
    for _ in range(20):
        assert get_random_recent_user(db, 1, ctx.privacy.opted_out)["user_id"] == 5


async def test_kanmanilla_and_navi_refuse_opted_out_names(db):
    ctx = make_ctx(db, llm=FakeLLM())
    ctx.privacy.mark_out(OTHER)
    gone = member(OTHER, "gone")
    i = interaction(ctx)
    await SummariesCog(ctx).kanmanilla_slash.callback(SummariesCog(ctx), i, gone)
    assert "opted out" in said(i) and ctx.llm.requests == []
    i = interaction(ctx)
    await PredictionsCog(ctx).navi_slash.callback(PredictionsCog(ctx), i, gone)
    assert "opted out" in said(i) and ctx.llm.requests == []


async def test_welcome_and_levelup_skip_opted_out_users(db):
    from navi.cogs.community import CommunityCog
    from navi.services.levels import maybe_announce_levelup

    ctx = make_ctx(db)
    ctx.privacy.mark_out(OTHER)
    joiner = SimpleNamespace(id=OTHER, display_name="gone", guild=MagicMock())
    await CommunityCog(ctx).on_member_join(joiner)
    assert joiner.guild.fetch_member.call_count == 0 and get_user_profile(db, OTHER) is None
    chan = MagicMock(); chan.send = AsyncMock()
    upsert_user(db, OTHER, "gone"); award(db, OTHER, 0, 5000, reason="x")
    await maybe_announce_levelup(ctx, "<@88>", OTHER, chan)
    assert chan.send.await_count == 0


async def test_lucky_draw_candidates_exclude_opted_out(db, monkeypatch):
    from navi.services.lucky_draw import run_lucky_draw

    ctx = make_ctx(db)
    ctx.privacy.mark_out(OTHER)
    for uid in (OTHER, 5):
        upsert_user(db, uid, f"u{uid}")
    award(db, OTHER, 1000, reason="x"); award(db, 5, 10, reason="x")
    monkeypatch.setattr("navi.services.lucky_draw.get_active_user_ids_previous_day", lambda conn: [OTHER, 5])
    chan = MagicMock(); chan.send = AsyncMock()
    result = await run_lucky_draw(ctx, chan)
    assert "u5" in result and points(db, OTHER) == 1000


async def test_summ_mod_tldr_and_audit_drop_opted_out_users(db):
    llm = FakeLLM(text="summary")
    ctx = make_ctx(db, llm=llm)
    ctx.privacy.mark_out(OTHER)

    class History:
        def __init__(self, msgs): self.msgs = msgs
        def __call__(self, **kw):
            async def gen():
                for m in self.msgs:
                    yield m
            return gen()

    msgs = [SimpleNamespace(author=member(OTHER, "gone"), content="secret chatter", created_at=datetime.now(timezone.utc)),
            SimpleNamespace(author=member(5, "ben"), content="public chatter", created_at=datetime.now(timezone.utc))]
    i = interaction(ctx)
    i.channel = SimpleNamespace(history=History(msgs))
    await SummariesCog(ctx).summ_slash.callback(SummariesCog(ctx), i, 30, None, None, False)
    prompt = llm.requests[0]["req"].prompt
    assert "public chatter" in prompt and "secret chatter" not in prompt and "gone" not in prompt

    thread = MagicMock(spec=discord.Thread); thread.history = History(msgs); thread.name = "t"
    i = interaction(ctx, channel=thread)
    await ModerationCog(ctx).mod_tldr_slash.callback(ModerationCog(ctx), i)
    prompt = llm.requests[-1]["req"].prompt
    assert "public chatter" in prompt and "secret chatter" not in prompt

    audit_target = member(OTHER, "gone")
    for flag, expected in ((False, 0), (True, 1)):
        ctx.settings.set("privacy.audit_includes_optouts", flag)
        before = len(llm.requests)
        i = interaction(ctx, channel=SimpleNamespace(history=History([SimpleNamespace(author=audit_target, content="rule break", created_at=datetime.now(timezone.utc))]), name="gen"))
        await ModerationCog(ctx).audit_slash.callback(ModerationCog(ctx), i, audit_target, None)
        assert len(llm.requests) - before == expected, flag


async def test_link_summary_reaction_ignored_for_opted_out_author_or_reactor(db):
    ctx = make_ctx(db, llm=FakeLLM())
    ctx.privacy.mark_out(OTHER)
    page = MagicMock(); page.author = member(OTHER); page.content = "https://example.com"; page.reply = AsyncMock()
    channel = MagicMock(); channel.fetch_message = AsyncMock(return_value=page)
    ctx.bot.get_channel = lambda cid: channel
    for author, reactor in ((OTHER, 5), (5, OTHER)):
        page.author = member(author)
        payload = SimpleNamespace(user_id=reactor, message_id=1, channel_id=2, emoji="📰", guild_id=3)
        ctx.bot.user.id = 999
        await SummariesCog(ctx).on_raw_reaction_add(payload)
        assert page.reply.await_count == 0 and ctx.llm.requests == []


def test_partner_api_does_not_recreate_a_profile_for_an_opted_out_user(db):
    from fastapi.testclient import TestClient

    from navi.api.partner import create_app

    ctx = make_ctx(db)
    ctx.privacy.mark_out(OTHER)
    os.environ["PARTNER_BOT_API_KEY"] = "k"
    os.environ["BOT_INTERNAL_SECRET"] = "s"
    client = TestClient(create_app(db, None, ctx.settings, ctx.privacy))
    r = client.post("/score", json={"user_id": OTHER, "guild_id": 1, "username": "gone", "points": 50, "game_id": "g1"},
                    headers={"Authorization": "Bearer k"})
    assert r.json()["status"] == "opted_out" and get_user_profile(db, OTHER) is None
    r = client.post("/internal/boli/award", json={"game_id": "b1", "awards": {str(OTHER): 10, "5": 10}}, headers={"X-Internal-Secret": "s"})
    assert get_user_profile(db, OTHER) is None and get_user_profile(db, 5)["external_boli"] == 10


# ------------------------------------------------------------------------------ the commands themselves

async def test_privacy_commands_flow(db, tmp_path):
    ctx = make_ctx(db)
    ctx.privacy = Privacy(connect_privacy(tmp_path / "p.db"))
    upsert_user(db, ME, "me"); award(db, ME, 20, reason="x")
    group = PrivacyGroup()
    i = interaction(ctx, user=member(ME))
    await PrivacyGroup.opt_out.callback(group, i)
    text, kwargs = i.response.send_message.await_args.args[0], i.response.send_message.await_args.kwargs
    assert "permanently deletes" in text and "fresh profile" in text and "72 hours" in text
    view: OptOutView = kwargs["view"]
    assert view.timeout == 60 and kwargs["ephemeral"] is True
    stranger = interaction(ctx, user=member(5)); assert await view.interaction_check(stranger) is False
    assert get_user_profile(db, ME) is not None                          # nothing happens before Confirm
    confirm = interaction(ctx, user=member(ME))
    await view.confirm.callback(confirm)
    assert ctx.privacy.is_opted_out(ME) and get_user_profile(db, ME) is None
    assert "opted out" in confirm.edit_original_response.await_args.kwargs["content"]
    i = interaction(ctx, user=member(ME)); await PrivacyGroup.status.callback(group, i)
    assert "opted out" in said(i)
    i = interaction(ctx, user=member(ME)); await PrivacyGroup.opt_in.callback(group, i)
    assert "opt back in from" in said(i) and ctx.privacy.is_opted_out(ME)         # cooldown (7 days) is respected
    i = interaction(ctx, user=member(ME)); await PrivacyGroup.opt_out.callback(group, i)
    assert "already opted out" in said(i)


async def test_opt_out_is_blocked_while_strikes_exist(db):
    ctx = make_ctx(db)
    upsert_user(db, ME, "me")
    db.execute("UPDATE users SET strikes = 1 WHERE user_id = ?", [ME]); db.commit()
    group = PrivacyGroup()
    i = interaction(ctx, user=member(ME))
    await PrivacyGroup.opt_out.callback(group, i)
    assert "strikes" in said(i) and "view" not in i.response.send_message.await_args.kwargs
    ctx.settings.set("privacy.block_optout_with_strikes", False)
    i = interaction(ctx, user=member(ME))
    await PrivacyGroup.opt_out.callback(group, i)
    assert "permanently deletes" in said(i)


async def test_cancel_and_timeout_delete_nothing(db):
    ctx = make_ctx(db)
    upsert_user(db, ME, "me")
    view = OptOutView(ctx, ME)
    i = interaction(ctx, user=member(ME))
    await view.cancel.callback(i)
    assert get_user_profile(db, ME) is not None and not ctx.privacy.is_opted_out(ME)
    view2 = OptOutView(ctx, ME); view2.message = MagicMock(); view2.message.edit = AsyncMock()
    await view2.on_timeout()
    assert "Nothing was deleted" in view2.message.edit.await_args.kwargs["content"] and not ctx.privacy.is_opted_out(ME)
