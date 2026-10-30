"""on_ready wiring against fakes: DB, LLM router, settings, tasks - then a clean shutdown."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import navi.app as app
from navi.db.connection import init_db  # noqa: F401  (ensures module import order)
from tests.legacy.harness import FakeUser, make_config, make_message


async def test_on_ready_initialises_everything_and_shutdown_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr("navi.db.connection.DB_PATH", tmp_path / "navi.db")
    monkeypatch.setattr(app, "do_backup", lambda: "backup")
    ran = []

    async def fake_api(db, allowed_guild_id=None):
        ran.append("api")

    monkeypatch.setattr(app, "run_api_server", fake_api)
    monkeypatch.setattr("navi.llm.gemini.GeminiProvider.verify_model_sync", lambda self: (self.model, None))

    bot, ctx = app.build(make_config(free_api_key="k", owner_id=7, guild_id=3))
    bot.tree.sync = AsyncMock()
    bot._connection.user = SimpleNamespace(id=999, mentioned_in=lambda m: False)
    await bot.on_ready()

    assert ctx.db is not None and ctx.llm is not None
    assert ctx.llm.provider.key_names == ["free"] and ctx.llm.free_tier_mode is True
    assert ctx.settings.feat("feature_curses") is True
    assert set(ctx.tasks) == {"backup", "last_seen_flush", "lucky_draw", "market_hourly", "partner_api", "retention"}
    bot.tree.sync.assert_awaited_once()

    # a message flows through the pipeline against the real temp database
    msg = make_message(FakeUser(11, "tester"), "hello there")
    await bot.on_message(msg)
    assert ctx.db.execute("SELECT display_name FROM users WHERE user_id=11").fetchone()[0] == "tester"
    assert 11 in ctx.state.last_seen_pending

    await app.shutdown(ctx)
    await asyncio.sleep(0)
    assert ctx.tasks == {}
    assert ran in ([], ["api"])


async def test_config_error_dm_goes_to_owner(tmp_path, monkeypatch):
    monkeypatch.setattr("navi.db.connection.DB_PATH", tmp_path / "navi.db")
    monkeypatch.setattr(app, "do_backup", lambda: "backup")

    async def fake_api(db, allowed_guild_id=None):
        return None

    monkeypatch.setattr(app, "run_api_server", fake_api)
    monkeypatch.setattr("navi.llm.gemini.GeminiProvider.verify_model_sync", lambda self: (self.model, None))
    sent = []

    class Owner:
        async def send(self, text):
            sent.append(text)

    bot, ctx = app.build(make_config(free_api_key="k", owner_id=7))
    bot.tree.sync = AsyncMock()
    bot.fetch_user = AsyncMock(return_value=Owner())
    await bot.on_ready()
    from navi.llm.base import LLMError

    ctx.llm._handle_config_error("free key", LLMError("config", "403 PERMISSION_DENIED"))
    await asyncio.sleep(0.05)
    assert len(sent) == 1 and "403" in sent[0]
    bot.fetch_user.assert_awaited_with(7)
    await app.shutdown(ctx)
