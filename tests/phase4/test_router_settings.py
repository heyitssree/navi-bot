"""The LLM router reads ai.* settings at use time."""
from tests.phase1.test_llm_router import REQ, Clock, FakeProvider, api_error
from navi.llm.base import LLMRequest
from navi.llm.router import LLMRouter
from navi.settings.store import Settings


def make(free="ok", paid=None, **kw):
    prov = FakeProvider(free, paid)
    settings = Settings()
    router = LLMRouter(prov, settings=settings, clock=Clock(), rpm_limit=1000, **kw)
    return router, prov, settings


async def call(r, **kw):
    return await r.generate(REQ, fallback="FB", **kw)


async def test_provider_off_means_fallbacks_only():
    r, prov, s = make()
    s.set("ai.provider", "off")
    res = await call(r)
    assert (res.text, res.outcome, prov.calls["free"]) == ("FB", "off", 0)
    s.set("ai.provider", "gemini")
    assert (await call(r)).text == "ok"


async def test_free_only_setting_blocks_the_paid_key():
    r, prov, s = make(free=api_error(429, "RESOURCE_EXHAUSTED"), paid="paid-reply")
    s.set("ai.gemini_keys", "free_only")
    assert (await call(r)).text == "FB" and prov.calls["paid"] == 0
    s.set("ai.gemini_keys", "free_then_paid")
    assert (await call(r)).text == "paid-reply"


async def test_rpm_budget_is_read_live():
    r, prov, s = make()
    s.set("ai.rpm_budget", 2)
    assert [(await call(r)).outcome for _ in range(3)] == ["ok", "ok", "budget"]
    s.set("ai.rpm_budget", 50)
    assert (await call(r)).outcome == "ok"


async def test_daily_call_cap_is_a_hard_stop_and_can_be_seeded():
    r, prov, s = make()
    s.set("ai.daily_call_cap", 2)
    r.seed_daily_calls(1)
    assert (await call(r)).outcome == "ok"
    res = await call(r)
    assert (res.outcome, res.text) == ("cap", "FB") and prov.calls["free"] == 1
    assert r.status_dict()["daily_calls"] == 2


async def test_temperature_tokens_and_model_override_reach_the_provider():
    seen = []

    class Spy(FakeProvider):
        async def generate(self, req, key=None):
            seen.append((req.temperature, req.max_tokens, self.model))
            return await super().generate(req, key)

    prov = Spy("ok")
    s = Settings()
    r = LLMRouter(prov, settings=s, clock=Clock(), rpm_limit=1000)
    await r.generate(LLMRequest(purpose="qa", system="s", prompt="p"), fallback="FB")
    await r.generate(LLMRequest(purpose="summary", system="s", prompt="p"), fallback="FB")
    s.set("ai.temperature", 0.2); s.set("ai.max_output_tokens", 50); s.set("ai.model", "custom-model")
    await r.generate(LLMRequest(purpose="qa", system="s", prompt="p"), fallback="FB")
    assert seen == [(0.6, 200, "fake-model"), (0.6, 800, "fake-model"), (0.2, 50, "custom-model")]


async def test_per_user_qa_cooldown_and_daily_cap():
    clk = Clock()
    prov = FakeProvider("ok")
    s = Settings()
    r = LLMRouter(prov, settings=s, clock=clk, rpm_limit=1000)
    s.set("ai.qa_cooldown_seconds", 30); s.set("ai.qa_daily_cap", 3)
    first = await r.generate(REQ, fallback="FB", user_id=1, name="Asha")
    assert first.outcome == "ok"
    second = await r.generate(REQ, fallback="FB", user_id=1, name="Asha")
    assert second.outcome == "user_cooldown" and "Asha" in second.text and prov.calls["free"] == 1
    assert (await r.generate(REQ, fallback="FB", user_id=2, name="Ben")).outcome == "ok"      # other users unaffected
    clk.t += 31
    assert (await r.generate(REQ, fallback="FB", user_id=1, name="Asha")).outcome == "ok"
    clk.t += 31
    assert (await r.generate(REQ, fallback="FB", user_id=1, name="Asha")).outcome == "ok"     # third allowed call
    clk.t += 31
    capped = await r.generate(REQ, fallback="FB", user_id=1, name="Asha")
    assert capped.outcome == "user_daily_cap" and "tomorrow" in capped.text.lower() or "midnight" in capped.text.lower()


async def test_limits_only_apply_to_qa_like_purposes():
    r, prov, s = make()
    s.set("ai.qa_cooldown_seconds", 600)
    summary = LLMRequest(purpose="summary", system="s", prompt="p")
    for _ in range(3):
        assert (await r.generate(summary, fallback="FB", user_id=1)).outcome == "ok"


def test_router_without_settings_keeps_constructor_behaviour():
    r = LLMRouter(FakeProvider("ok"), rpm_limit=7)
    assert r.rpm == 7 and r.is_enabled and not r.is_free_only
