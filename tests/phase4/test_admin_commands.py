"""/admin commands and the panel, driven with fake Discord interactions."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from navi.cogs.admin import AdminGroup, key_autocomplete
from navi.cogs.admin_panel import PAGE_SIZE, PanelView, settings_in
from navi.cogs.admin_review import ReviewView
from navi.db.repos.content import set_content_status
from navi.db.repos.permissions import has_permission
from navi.db.repos.users import get_user_profile, upsert_user
from navi.services.permissions import can_use_admin
from navi.settings.registry import CATEGORIES, SETTINGS
from tests.legacy.harness import FakeUser, make_ctx


def interaction(ctx, user_id=1, guild_id=500):
    i = MagicMock()
    i.client = ctx.bot
    i.user = SimpleNamespace(id=user_id, display_name="owner", roles=[])
    i.guild_id = guild_id
    i.response.send_message = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.response.send_modal = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.is_done = lambda: False
    i.followup.send = AsyncMock()
    return i


def reply(i):
    args, kwargs = i.response.send_message.await_args
    return (args[0] if args else kwargs.get("content", "")), kwargs


@pytest.fixture()
def ctx(db):
    return make_ctx(db, owner_id=1)


async def run(command, *args, ctx, **kw):
    i = interaction(ctx, **kw)
    await command.callback(None, i, *args)
    return i


# -------------------------------------------------------------------- permission

async def test_can_use_admin(ctx):
    assert await can_use_admin(ctx, SimpleNamespace(id=1, roles=[]))
    ctx.bot.application_info.return_value = SimpleNamespace(owner=SimpleNamespace(id=99))
    assert await can_use_admin(ctx, SimpleNamespace(id=99, roles=[]))
    assert not await can_use_admin(ctx, SimpleNamespace(id=2, roles=[SimpleNamespace(id=7)]))
    ctx.settings.set("system.panel_role", 7)
    assert await can_use_admin(ctx, SimpleNamespace(id=2, roles=[SimpleNamespace(id=7)]))
    assert not await can_use_admin(ctx, SimpleNamespace(id=3, roles=[SimpleNamespace(id=8)]))


async def test_group_check_rejects_strangers(ctx):
    ctx.bot.application_info.return_value = SimpleNamespace(owner=SimpleNamespace(id=99))
    group = AdminGroup()
    i = interaction(ctx, user_id=5)
    assert await group.interaction_check(i) is False and "owner-only" in reply(i)[0]
    assert await group.interaction_check(interaction(ctx, user_id=1)) is True


# -------------------------------------------------------------------- set / get / reset

async def test_set_get_reset_roundtrip(ctx):
    i = await run(AdminGroup.set_cmd, "chance.kochi_reply", "0.5", ctx=ctx)
    assert "0.5" in reply(i)[0] and ctx.settings.get("chance.kochi_reply") == 0.5
    i = await run(AdminGroup.get_cmd, "chance.kochi_reply", ctx=ctx)
    assert "changed" in reply(i)[0] and "Default: 0.28" in reply(i)[0]
    i = await run(AdminGroup.reset_cmd, "chance.kochi_reply", ctx=ctx)
    assert ctx.settings.get("chance.kochi_reply") == 0.28 and "reset" in reply(i)[0]


async def test_set_rejects_bad_values_unknown_and_hidden_keys(ctx):
    assert "between" in reply(await run(AdminGroup.set_cmd, "chance.kochi_reply", "7", ctx=ctx))[0]
    assert "Unknown setting" in reply(await run(AdminGroup.set_cmd, "chance.nope", "1", ctx=ctx))[0]
    assert "internal" in reply(await run(AdminGroup.set_cmd, "state.lucky_draw_last_date", "x", ctx=ctx))[0]
    assert ctx.settings.get("chance.kochi_reply") == 0.28


async def test_autocomplete_filters_and_hides_internal_keys(ctx):
    names = [c.value for c in await key_autocomplete(interaction(ctx), "backfire")]
    assert names == ["chance.backfire_mild", "chance.backfire_moderate", "chance.backfire_severe"]
    assert len(await key_autocomplete(interaction(ctx), "")) == 25
    assert all(c.value != "state.lucky_draw_last_date" for c in await key_autocomplete(interaction(ctx), "lucky"))


async def test_killswitch_and_testing(ctx):
    await run(AdminGroup.killswitch, "on", ctx=ctx)
    assert ctx.settings.get("system.killswitch") is True
    await run(AdminGroup.killswitch, "off", ctx=ctx)
    assert ctx.settings.get("system.killswitch") is False
    await run(AdminGroup.testing, "on", ctx=ctx, guild_id=500)
    await run(AdminGroup.testing, "on", ctx=ctx, guild_id=501)
    await run(AdminGroup.testing, "off", ctx=ctx, guild_id=500)
    assert ctx.settings.get("system.testing_guilds") == [501] and ctx.settings.is_testing_guild(501)


async def test_status_embed(ctx, tmp_path, monkeypatch):
    import navi.cogs.admin as admin
    from navi.llm.router import LLMRouter
    from tests.phase1.test_llm_router import FakeProvider

    ctx.llm = LLMRouter(FakeProvider("ok"), settings=ctx.settings)
    monkeypatch.setattr(admin, "DB_PATH", tmp_path / "x.db")
    i = await run(AdminGroup.status, ctx=ctx)
    embed = i.followup.send.await_args.kwargs["embed"]
    text = " ".join(f"{f.name} {f.value}" for f in embed.fields)
    assert "Provider: **gemini**" in text and "closed" in text and "1500" in text and "users" in text


# -------------------------------------------------------------------- users

async def test_user_points_set_add_subtract_are_ledger_entries(ctx):
    member = FakeUser(7, "asha")
    await run(AdminGroup.user_points, member, "set", 100, ctx=ctx)
    await run(AdminGroup.user_points, member, "add", 25, ctx=ctx)
    await run(AdminGroup.user_points, member, "subtract", 5, ctx=ctx)
    assert get_user_profile(ctx.db, 7)["boli_points"] == 120
    rows = ctx.db.execute("SELECT delta, reason FROM points_ledger WHERE user_id=7 ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(100, "admin"), (25, "admin"), (-5, "admin")]


async def test_strikes_and_game_attempts_reset(ctx):
    from navi.db.repos.counters import get_total_game_daily_count, increment_game_daily_count
    from navi.db.repos.users import get_user_strikes, increment_user_strikes

    for uid in (7, 8):
        upsert_user(ctx.db, uid, f"u{uid}"); increment_user_strikes(ctx.db, uid)
    await run(AdminGroup.user_strikes_reset, FakeUser(7), ctx=ctx)
    assert (get_user_strikes(ctx.db, 7), get_user_strikes(ctx.db, 8)) == (0, 1)
    i = await run(AdminGroup.user_strikes_reset, None, ctx=ctx)
    assert get_user_strikes(ctx.db, 8) == 0 and "1" in reply(i)[0]
    increment_game_daily_count(ctx.db, 7, "flip")
    await run(AdminGroup.user_game_attempts_reset, FakeUser(7), "gambling", ctx=ctx)
    assert get_total_game_daily_count(ctx.db, 7) == 0


async def test_teach_allow_revoke_list(ctx):
    await run(AdminGroup.teach_allow, FakeUser(7, "asha"), ctx=ctx)
    assert has_permission(ctx.db, 7, "teach")
    assert "<@7>" in reply(await run(AdminGroup.teach_list, ctx=ctx))[0]
    await run(AdminGroup.teach_revoke, FakeUser(7, "asha"), ctx=ctx)
    assert not has_permission(ctx.db, 7, "teach") and "none" in reply(await run(AdminGroup.teach_list, ctx=ctx))[0]


# -------------------------------------------------------------------- export / import / review

async def test_export_and_import(ctx):
    ctx.settings.set("feature.welcome", False)
    i = await run(AdminGroup.export, ctx=ctx)
    file = i.response.send_message.await_args.kwargs["file"]
    data = json.loads(file.fp.read().decode())
    assert data["settings"] == {"feature.welcome": False}
    ctx.settings.reset("feature.welcome")
    att = MagicMock(); att.size = 100; att.read = AsyncMock(return_value=json.dumps(data).encode())
    i = await run(AdminGroup.import_cmd, att, ctx=ctx)
    assert ctx.settings.get("feature.welcome") is False and "Imported **1**" in reply(i)[0]
    big = MagicMock(); big.size = 10**6
    assert "too large" in reply(await run(AdminGroup.import_cmd, big, ctx=ctx))[0]


async def test_review_queue_approve_reject_and_next_batch(ctx):
    db = ctx.db
    for n in range(7):
        db.execute("INSERT INTO content (kind, text, status, source) VALUES ('curse_back', ?, 'pending', 'llm')", [f"t{n} {{user}}"])
    db.execute("INSERT INTO knowledge (category, term, description, status, submitted_by) VALUES ('food', 'Pazham Pori', 'banana fritter, best with chaya', 'pending', 7)")
    db.commit()
    view = ReviewView(ctx, 1)
    assert len(view.items) == 5 and view.items[0]["source"] == "knowledge"            # /teach entries come first
    assert "Pazham Pori" in view.embed().description
    i = interaction(ctx)
    await view.decide(i, 0, True)
    await view.decide(i, 1, False)
    assert db.execute("SELECT status, approved_by FROM knowledge").fetchone()[0] == "active"
    assert db.execute("SELECT status FROM content WHERE text LIKE 't0%'").fetchone()[0] == "rejected"
    for n in range(2, 5):
        await view.decide(i, n, True)
    assert len(view.done) == 0 and len(view.items) == 3                                  # whole batch done: next one loaded
    assert db.execute("SELECT COUNT(*) FROM content WHERE status='pending'").fetchone()[0] == 3
    assert (await view.interaction_check(interaction(ctx, user_id=5))) is False
    for item in view.items:
        set_content_status(db, item["id"], "active", 1)
    assert ReviewView(ctx, 1).embed().title == "Review queue" and "Nothing" in ReviewView(ctx, 1).embed().description


# -------------------------------------------------------------------- panel

def pick(view, item_type):
    return next(c for c in view.children if isinstance(c, item_type))


def choose(select, value):
    select._values = [value]
    return select


async def test_panel_home_category_setting_toggle_edit_reset(ctx):
    view = PanelView(ctx, 1)
    assert view.embed().title == "⚙️ Navi settings" and len(view.embed().fields) == len(CATEGORIES)
    i = interaction(ctx)
    await choose(pick(view, discord.ui.Select), "Features").callback(i)
    assert view.mode == "category" and "Gambling" in view.embed().description
    await choose(pick(view, discord.ui.Select), "feature.gambling").callback(i)
    assert view.mode == "setting" and view.embed().title == "Gambling"
    toggle = pick(view, discord.ui.Button)
    assert toggle.label == "Turn off"
    await toggle.callback(i)
    assert ctx.settings.get("feature.gambling") is False and "now **off**" in view.notice and pick(view, discord.ui.Button).label == "Turn on"
    reset = next(c for c in view.children if getattr(c, "label", "") == "Reset to default")
    assert not reset.disabled
    await reset.callback(i)
    assert ctx.settings.get("feature.gambling") is True and "reset" in view.notice
    back = next(c for c in view.children if getattr(c, "label", "") == "Back")
    await back.callback(i)
    assert view.mode == "category"
    await next(c for c in view.children if getattr(c, "label", "") == "Back").callback(i)
    assert view.mode == "home"


async def test_panel_modal_validates_and_applies(ctx):
    view = PanelView(ctx, 1)
    view.go_setting("chance.kochi_reply"); view._rebuild()
    i = interaction(ctx)
    await pick(view, discord.ui.Button).callback(i)                    # the Edit button
    modal = i.response.send_modal.await_args.args[0]
    modal.value._value = "7"
    await modal.on_submit(i)
    assert view.notice.startswith("❌") and ctx.settings.get("chance.kochi_reply") == 0.28
    modal.value._value = "0.4"
    await modal.on_submit(i)
    assert view.notice.startswith("✅") and ctx.settings.get("chance.kochi_reply") == 0.4
    chances = next(f for f in PanelView(ctx, 1).embed().fields if f.name == "Chances")
    assert "✏️ 1" in chances.value


async def test_panel_choice_channel_and_role_controls(ctx):
    i = interaction(ctx)
    view = PanelView(ctx, 1)
    view.go_setting("ai.provider"); view._rebuild()
    await choose(pick(view, discord.ui.Select), "off").callback(i)
    assert ctx.settings.get("ai.provider") == "off"
    view.go_setting("channel.bot_commands"); view._rebuild()
    picker = pick(view, discord.ui.ChannelSelect)
    picker._values = [SimpleNamespace(id=321)]
    await picker.callback(i)
    assert ctx.settings.get("channel.bot_commands") == 321 and "<#321>" in view.notice
    view.go_setting("system.panel_role"); view._rebuild()
    role = pick(view, discord.ui.RoleSelect)
    role._values = [SimpleNamespace(id=654)]
    await role.callback(i)
    assert ctx.settings.get("system.panel_role") == 654


async def test_panel_only_serves_its_invoker_and_paginates(ctx):
    view = PanelView(ctx, 1)
    stranger = interaction(ctx, user_id=9)
    assert await view.interaction_check(stranger) is False and "someone else" in reply(stranger)[0]
    assert await view.interaction_check(interaction(ctx, user_id=1)) is True
    assert view.timeout == 600
    big = max(CATEGORIES, key=lambda c: len(settings_in(c)))
    view.go_category(big, 0); view._rebuild()
    assert len(pick(view, discord.ui.Select).options) <= PAGE_SIZE


async def test_every_visible_setting_has_a_working_panel_page(ctx):
    for s in SETTINGS:
        if s.hidden:
            continue
        view = PanelView(ctx, 1)
        view.go_setting(s.key); view._rebuild()
        emb = view.embed()
        assert emb.title == s.label and view.children, s.key
        control = {"bool": discord.ui.Button, "choice": discord.ui.Select, "channel": discord.ui.ChannelSelect,
                   "role": discord.ui.RoleSelect}.get(s.kind, discord.ui.Button)
        assert any(isinstance(c, control) for c in view.children), s.key
        assert any(getattr(c, "label", "") == "Back" for c in view.children), s.key


async def test_settings_changes_notify_observers_so_live_objects_follow(ctx):
    seen = []
    ctx.settings.on_change(lambda s, v: seen.append(s.key))
    view = PanelView(ctx, 1)
    view.apply("ai.rpm_budget", 77, interaction(ctx))
    assert seen == ["ai.rpm_budget"] and ctx.settings.get("ai.rpm_budget") == 77
