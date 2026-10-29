import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from navi.cogs.summaries import SummariesCog
from navi.data.messages import FALLBACK_MESSAGES
from navi.db.repos.content import get_todays_user_prediction, save_user_prediction
from navi.db.repos.users import get_user_profile, upsert_user
from navi.services.predictions import get_navi_prediction
from tests.legacy.harness import FakeLLM, FakeUser, make_ctx

FALLBACKS = FALLBACK_MESSAGES


@pytest.fixture()
def pred(db, monkeypatch):
    llm = FakeLLM()
    ctx = make_ctx(db, llm=llm)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    return ctx, llm


def _seed_today(db, uid=5, text="today's cached"):
    upsert_user(db, uid, "u")
    save_user_prediction(db, uid, text)


async def test_first_call_without_cache_calls_llm_and_saves(pred):
    ctx, api = pred
    out = await get_navi_prediction(ctx, 5, "Asha", usage_count=1)
    assert out == "LLM says hi" and len(api.requests) == 1
    assert api.requests[0]["cache_type"] == "navi"
    assert api.requests[0]["req"].purpose == "prediction"
    assert get_todays_user_prediction(ctx.db, 5) == "LLM says hi"
    assert get_user_profile(ctx.db, 5)["prediction_count"] == 1
    assert get_user_profile(ctx.db, 5)["rashi"]  # rashi assigned


async def test_first_call_reuses_daily_cache_at_configured_chance(pred, monkeypatch):
    ctx, api = pred
    _seed_today(ctx.db)
    monkeypatch.setattr(random, "random", lambda: 0.0)  # < 0.50 default
    assert await get_navi_prediction(ctx, 5, "Asha", 1) == "today's cached"
    assert api.requests == []
    monkeypatch.setattr(random, "random", lambda: 0.99)
    assert await get_navi_prediction(ctx, 5, "Asha", 1) == "LLM says hi"
    assert len(api.requests) == 1


async def test_second_call_uses_35_percent_cache(pred, monkeypatch):
    ctx, api = pred
    _seed_today(ctx.db)
    monkeypatch.setattr(random, "random", lambda: 0.34)
    assert await get_navi_prediction(ctx, 5, "Asha", 2) == "today's cached"
    assert api.requests == []
    monkeypatch.setattr(random, "random", lambda: 0.35)
    assert await get_navi_prediction(ctx, 5, "Asha", 2) == "LLM says hi"


async def test_third_call_never_calls_llm(pred):
    ctx, api = pred
    _seed_today(ctx.db)
    assert await get_navi_prediction(ctx, 5, "Asha", 3) == "today's cached"
    assert await get_navi_prediction(ctx, 5, "Asha", 7) == "today's cached"
    assert api.requests == [] and api.cache_only_calls == []


async def test_third_call_without_daily_uses_pool_cache_only(pred):
    ctx, api = pred
    upsert_user(ctx.db, 6, "u")
    assert await get_navi_prediction(ctx, 6, "Asha", 3) == "POOL"
    assert api.requests == [] and len(api.cache_only_calls) == 1
    assert api.cache_only_calls[0]["cache_type"] == "navi"


async def test_fallback_or_cached_result_is_not_saved(pred):
    ctx, api = pred
    api.text, api.from_cache = FALLBACKS[0], False
    await get_navi_prediction(ctx, 5, "Asha", 1)
    assert get_todays_user_prediction(ctx.db, 5) is None
    api.text, api.from_cache = "from pool", True
    await get_navi_prediction(ctx, 5, "Asha", 1)
    assert get_todays_user_prediction(ctx.db, 5) is None


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
    api = FakeLLM(text="SUMMARY")
    ctx = make_ctx(None, llm=api)
    inter = MagicMock()
    inter.client = ctx.bot
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.channel.history = _History(msgs)
    await SummariesCog(ctx).summ_slash.callback(SummariesCog(ctx), inter, 30, None, None, False)
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
    prompt = api.requests[0]["req"].prompt
    assert "u5: second kept" in prompt
    assert "u1: hello [mentioned-user] and [mentioned-user] and [mentioned-user] and [mentioned-user]" in prompt
    assert "/summ" not in prompt and "I am a bot" not in prompt and "u4" not in prompt
    assert prompt.index("u5:") < prompt.index("u1:")  # chronological (reversed from newest-first)
    assert "last 2 messages" in inter.followup.send.await_args.args[0]


async def test_summ_all_filtered_sends_notice_without_llm(monkeypatch):
    api, inter = await _run_summ(monkeypatch, [_m(3, "bot", is_bot=True), _m(2, "/x")])
    assert api.requests == []
    assert "Nothing to summarise" in inter.followup.send.await_args.args[0]


async def test_summ_empty_history(monkeypatch):
    api, inter = await _run_summ(monkeypatch, [])
    assert api.requests == []
    assert "No messages found" in inter.followup.send.await_args.args[0]


async def test_summ_uses_qa_cache_type_today(monkeypatch):
    """Characterises Phase-1 bug: /summ passes cache_type='qa' (unrelated cache fallback)."""
    api, _ = await _run_summ(monkeypatch, [_m(1, "hi")])
    assert api.requests[0]["cache_type"] == "qa"
