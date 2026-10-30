import asyncio

from navi.app import shutdown
from navi.config import load_ssm_parameters
from navi.handlers import pipeline
from navi.handlers.context_reply import handle_context_reply
from navi.handlers.curse_commands import handle_chunk_command, handle_navi_command
from navi.handlers.kochi import handle_kochi
from navi.handlers.mention_qa import handle_mention_qa
from navi.handlers.passive_curse import handle_passive_curse
from navi.handlers.shortcuts import handle_shortcut
from navi.handlers.slang_points import handle_slang_points
from navi.handlers.vibe import handle_vibe
from tests.legacy.harness import FakeUser, make_ctx, make_message


def test_pipeline_order_is_the_documented_order():
    assert pipeline.HANDLERS == [
        pipeline.track_user, handle_shortcut, handle_vibe, handle_slang_points,
        handle_kochi, handle_context_reply, handle_mention_qa, handle_navi_command, handle_chunk_command, handle_passive_curse,
    ]
    doc = pipeline.__doc__
    for word in ("shortcuts", "mention_qa", "curse command", "bless command", "passive_curse"):
        assert word in doc


async def test_guards_ignore_bots_killswitch_and_uninitialised_db(db):
    calls = []

    async def spy(ctx, message):
        calls.append(1)
        return False

    original = pipeline.HANDLERS[:]
    pipeline.HANDLERS[:] = [spy]
    try:
        ctx = make_ctx(db)
        await pipeline.on_message(ctx, make_message(FakeUser(1, is_bot=True), "hi"))
        ctx.settings.override("system.killswitch", True)
        await pipeline.on_message(ctx, make_message(FakeUser(1), "hi"))
        ctx.settings.override("system.killswitch", False)
        ctx.db = None
        await pipeline.on_message(ctx, make_message(FakeUser(1), "hi"))
        assert calls == []
        ctx.db = db
        await pipeline.on_message(ctx, make_message(FakeUser(1), "hi"))
        assert calls == [1]
    finally:
        pipeline.HANDLERS[:] = original


async def test_first_consuming_handler_stops_the_chain(db):
    order = []

    def mk(name, consume):
        async def h(ctx, message):
            order.append(name)
            return consume
        return h

    original = pipeline.HANDLERS[:]
    pipeline.HANDLERS[:] = [mk("a", False), mk("b", True), mk("c", False)]
    try:
        await pipeline.on_message(make_ctx(db), make_message(FakeUser(1), "hi"))
    finally:
        pipeline.HANDLERS[:] = original
    assert order == ["a", "b"]


class FakeSSM:
    def get_parameters_by_path(self, **kw):
        if kw.get("NextToken") == "t2":
            return {"Parameters": [{"Name": "/navi/prod/LLM_MODEL", "Value": "m"}]}
        return {"Parameters": [{"Name": "/navi/prod/DISCORD_TOKEN", "Value": "tok"},
                               {"Name": "/navi/prod/OWNER_ID", "Value": "1"}], "NextToken": "t2"}


def test_ssm_loading_sets_missing_variables_only(monkeypatch):
    for k in ("DISCORD_TOKEN", "LLM_MODEL", "OWNER_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OWNER_ID", "42")  # existing environment wins
    assert load_ssm_parameters("/navi/prod", client=FakeSSM()) == 2
    import os

    assert os.environ["DISCORD_TOKEN"] == "tok" and os.environ["LLM_MODEL"] == "m" and os.environ["OWNER_ID"] == "42"
    for k in ("DISCORD_TOKEN", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)


async def test_shutdown_cancels_tasks_flushes_and_closes_db(db, monkeypatch):
    import navi.app as app
    from navi.db.repos.users import upsert_user

    monkeypatch.setattr(app, "do_backup", lambda: "backup-path")
    ctx = make_ctx(db)
    upsert_user(db, 1, "a")
    ctx.state.last_seen_pending[1] = "2031-01-01 00:00:00"
    forever = asyncio.create_task(asyncio.sleep(3600), name="forever")
    ctx.tasks["forever"] = forever
    await shutdown(ctx)
    await asyncio.sleep(0)
    assert forever.cancelled() or forever.done()
    assert ctx.tasks == {}
    import sqlite3
    try:
        db.execute("SELECT 1")
        closed = False
    except sqlite3.ProgrammingError:
        closed = True
    assert closed
