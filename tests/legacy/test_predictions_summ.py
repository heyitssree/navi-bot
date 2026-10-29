from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot as navi
import schema
from tests.legacy.harness import FakeUser, install

FALLBACKS = navi.FALLBACK_MESSAGES


class FakeApiMgr:
    def __init__(self, text="LLM says hi", from_cache=False, pool="POOL"):
        self.calls, self.cache_only_calls = [], []
        self.text, self.from_cache, self.pool = text, from_cache, pool

    def call(self, **kw):
        self.calls.append(kw)
        return self.text, self.from_cache

    def call_cache_only(self, **kw):
        self.cache_only_calls.append(kw)
        return self.pool, True


@pytest.fixture()
def pred(db, monkeypatch):
    install(navi, monkeypatch, db)
    api = FakeApiMgr()
    monkeypatch.setattr(navi, "api_mgr", api)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(navi.asyncio, "sleep", no_sleep)
    return db, api


def _seed_today(db, uid=5, text="today's cached"):
    schema.upsert_user(db, uid, "u")
    schema.save_user_prediction(db, uid, text)


async def test_first_call_without_cache_calls_llm_and_saves(pred):
    db, api = pred
    out = await navi.get_navi_prediction(5, "Asha", usage_count=1)
    assert out == "LLM says hi" and len(api.calls) == 1
    assert api.calls[0]["cache_type"] == "navi"
    assert schema.get_todays_user_prediction(db, 5) == "LLM says hi"
    assert schema.get_user_profile(db, 5)["prediction_count"] == 1
    assert schema.get_user_profile(db, 5)["rashi"]  # rashi assigned


async def test_first_call_reuses_daily_cache_at_configured_chance(pred, monkeypatch):
    db, api = pred
    _seed_today(db)
    monkeypatch.setattr(navi.random, "random", lambda: 0.0)  # < 0.50 default
    assert await navi.get_navi_prediction(5, "Asha", 1) == "today's cached"
    assert api.calls == []
    monkeypatch.setattr(navi.random, "random", lambda: 0.99)
    assert await navi.get_navi_prediction(5, "Asha", 1) == "LLM says hi"
    assert len(api.calls) == 1


async def test_second_call_uses_35_percent_cache(pred, monkeypatch):
    db, api = pred
    _seed_today(db)
    monkeypatch.setattr(navi.random, "random", lambda: 0.34)
    assert await navi.get_navi_prediction(5, "Asha", 2) == "today's cached"
    assert api.calls == []
    monkeypatch.setattr(navi.random, "random", lambda: 0.35)
    assert await navi.get_navi_prediction(5, "Asha", 2) == "LLM says hi"


async def test_third_call_never_calls_llm(pred):
    db, api = pred
    _seed_today(db)
    assert await navi.get_navi_prediction(5, "Asha", 3) == "today's cached"
    assert await navi.get_navi_prediction(5, "Asha", 7) == "today's cached"
    assert api.calls == [] and api.cache_only_calls == []


async def test_third_call_without_daily_uses_pool_cache_only(pred):
    db, api = pred
    schema.upsert_user(db, 6, "u")
    assert await navi.get_navi_prediction(6, "Asha", 3) == "POOL"
    assert api.calls == [] and len(api.cache_only_calls) == 1
    assert api.cache_only_calls[0]["cache_type"] == "navi"


async def test_fallback_or_cached_result_is_not_saved(pred):
    db, api = pred
    api.text, api.from_cache = FALLBACKS[0], False
    await navi.get_navi_prediction(5, "Asha", 1)
    assert schema.get_todays_user_prediction(db, 5) is None
    api.text, api.from_cache = "from pool", True
    await navi.get_navi_prediction(5, "Asha", 1)
    assert schema.get_todays_user_prediction(db, 5) is None


# ------------------------------- /summ ----------------------------------

class _History:
    def __init__(self, msgs):
        self.msgs = msgs

    def __call__(self, limit):
        async def gen():
            for m in self.msgs:  # discord yields newest-first
                yield m
        return gen()


def _m(author, text, is_bot=False):
    a = FakeUser(author, f"u{author}", is_bot=is_bot)
    return SimpleNamespace(author=a, content=text)


async def _run_summ(monkeypatch, msgs):
    api = FakeApiMgr(text="SUMMARY")
    monkeypatch.setattr(navi, "api_mgr", api)
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.channel.history = _History(msgs)
    await navi.summ_slash.callback(inter, 30, None, None, False)
    return api, inter


async def test_summ_filters_bots_commands_and_scrubs_mentions(monkeypatch):
    newest_first = [
        _m(1, "hello <@123> and <#55> and <@&9> and <@!77>"),
        _m(2, "/summ", False),
        _m(3, "I am a bot", is_bot=True),
        _m(4, "   "),
        _m(5, "second kept"),
    ]
    api, inter = await _run_summ(monkeypatch, newest_first)
    prompt = api.calls[0]["prompt"]
    assert "u5: second kept" in prompt
    assert "u1: hello [mentioned-user] and [mentioned-user] and [mentioned-user] and [mentioned-user]" in prompt
    assert "/summ" not in prompt and "I am a bot" not in prompt and "u4" not in prompt
    assert prompt.index("u5:") < prompt.index("u1:")  # chronological (reversed from newest-first)
    assert "last 2 messages" in inter.followup.send.await_args.args[0]


async def test_summ_all_filtered_sends_notice_without_llm(monkeypatch):
    api, inter = await _run_summ(monkeypatch, [_m(3, "bot", is_bot=True), _m(2, "/x")])
    assert api.calls == []
    assert "Nothing to summarise" in inter.followup.send.await_args.args[0]


async def test_summ_empty_history(monkeypatch):
    api, inter = await _run_summ(monkeypatch, [])
    assert api.calls == []
    assert "No messages found" in inter.followup.send.await_args.args[0]


async def test_summ_uses_qa_cache_type_today(monkeypatch):
    """Characterises Phase-1 bug: /summ passes cache_type='qa' (unrelated cache fallback)."""
    api, _ = await _run_summ(monkeypatch, [_m(1, "hi")])
    assert api.calls[0]["cache_type"] == "qa"
