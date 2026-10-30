"""Phase 1 behaviour on the Phase 2 LLM layer: error classes, per-key cooldowns, breaker, owner alerts, model check."""
from types import SimpleNamespace

from google.genai import errors

from navi.llm.base import LLMError, LLMRequest, LLMResponse
from navi.llm.gemini import GeminiProvider, classify_error
from navi.llm.router import CircuitBreaker, LLMRouter

REQ = LLMRequest(purpose="qa", system="s", prompt="p")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def api_error(code, status=None, message="boom", details=None):
    body = {"error": {"code": code, "status": status, "message": message, "details": details or []}}
    return errors.APIError(code, body)


class FakeProvider:
    """Behaviour per key: a value, an exception (raised as classified LLMError), or a callable returning either."""

    name = "gemini"
    paid_keys = frozenset({"paid"})

    def __init__(self, free=None, paid=None):
        self.behaviour = {}
        if free is not None:
            self.behaviour["free"] = free
        if paid is not None:
            self.behaviour["paid"] = paid
        self.key_names = list(self.behaviour)
        self.model = "fake-model"
        self.calls = {k: 0 for k in self.behaviour}

    async def generate(self, req, key=None):
        self.calls[key] += 1
        b = self.behaviour[key]
        out = b() if callable(b) else b
        if isinstance(out, Exception):
            raise classify_error(out) if not isinstance(out, LLMError) else out
        return LLMResponse(out, 1, 1, self.name, self.model, 1)


def make(free=None, paid=None, clock=None, **kw):
    prov = FakeProvider(free, paid)
    return LLMRouter(prov, clock=clock or Clock(), **kw), prov


async def call(router):
    return await router.generate(REQ, fallback="FB")


# ---- classification ----

def test_classify():
    assert classify_error(api_error(429, "RESOURCE_EXHAUSTED")).kind == "rate_limited"
    for code in (400, 401, 403, 404):
        assert classify_error(api_error(code, "X")).kind == "config"
    for code in (500, 503):
        assert classify_error(api_error(code, "UNAVAILABLE")).kind == "server"
    assert classify_error(TimeoutError("t")).kind == "server"
    assert classify_error(ConnectionError("c")).kind == "server"


def test_retry_delay_from_details_and_message():
    e = api_error(429, "RESOURCE_EXHAUSTED", details=[{"@type": "x.RetryInfo", "retryDelay": "34s"}])
    assert classify_error(e).retry_after == 34.0
    e = api_error(429, "RESOURCE_EXHAUSTED", message="Please retry in 7.5s.")
    assert classify_error(e).retry_after == 7.5
    assert classify_error(api_error(429, "RESOURCE_EXHAUSTED")).retry_after == 20.0


# ---- rate limiting never trips the breaker ----

async def test_429_short_cooldown_not_breaker():
    clk = Clock()
    r, prov = make(free=api_error(429, "RESOURCE_EXHAUSTED", message="retry in 10s"), clock=clk, rpm_limit=1000)
    for _ in range(10):
        assert (await call(r)).text == "FB"
        clk.t += 1
    assert r.breaker.failures == 0 and not r.is_circuit_open
    assert prov.calls["free"] == 1  # key is cooling down; no hammering
    clk.t += 10  # cooldown over -> key is tried again
    await call(r)
    assert prov.calls["free"] == 2


async def test_429_on_free_falls_through_to_paid():
    r, _ = make(free=api_error(429, "RESOURCE_EXHAUSTED"), paid="hello")
    res = await call(r)
    assert res.text == "hello" and not res.from_cache
    assert r.active_key == "paid"


async def test_free_only_skips_paid_key():
    r, prov = make(free=api_error(429, "RESOURCE_EXHAUSTED"), paid="hello")
    r.free_only = True
    assert (await call(r)).text == "FB"
    assert prov.calls["paid"] == 0


# ---- config errors ----

async def test_404_opens_breaker_and_alerts_owner_once():
    clk = Clock()
    r, _ = make(free=api_error(404, "NOT_FOUND", message="model not found"), clock=clk, rpm_limit=1000)
    alerts = []
    r.on_config_error = alerts.append
    assert (await call(r)).text == "FB"
    assert r.is_circuit_open and len(alerts) == 1
    assert "model not found" in alerts[0]
    clk.t += 301  # breaker half-opens; probe fails again with config error
    await call(r)
    clk.t += 301
    await call(r)
    assert len(alerts) == 1  # within the hour: still a single DM
    clk.t += 3600
    await call(r)
    assert len(alerts) == 2


# ---- server errors / breaker ----

async def test_three_server_errors_open_five_minutes_then_probe():
    clk = Clock()
    state = {"fail": True}
    r, prov = make(free=lambda: api_error(503, "UNAVAILABLE") if state["fail"] else "ok", clock=clk, rpm_limit=1000)
    await call(r); await call(r)
    assert not r.is_circuit_open
    await call(r)
    assert r.is_circuit_open
    calls = prov.calls["free"]
    assert (await call(r)).text == "FB" and prov.calls["free"] == calls  # open: provider untouched
    clk.t += 299
    assert r.is_circuit_open
    clk.t += 2
    assert not r.is_circuit_open
    state["fail"] = False
    assert (await call(r)).text == "ok"  # half-open probe succeeds -> closed
    assert r.breaker.failures == 0 and not r.is_circuit_open


async def test_failed_probe_reopens():
    clk = Clock()
    r, _ = make(free=api_error(500, "INTERNAL"), clock=clk, rpm_limit=1000)
    for _ in range(3):
        await call(r)
    clk.t += 301
    await call(r)  # probe fails
    assert r.is_circuit_open


async def test_success_resets_failure_streak():
    state = {"n": 0}

    def beh():
        state["n"] += 1
        return "ok" if state["n"] == 3 else api_error(503, "UNAVAILABLE")

    r, _ = make(free=beh, rpm_limit=1000)
    for _ in range(5):
        await call(r)
    assert not r.is_circuit_open


def test_breaker_single_probe_only():
    clk = Clock()
    b = CircuitBreaker(clock=clk)
    b.trip()
    clk.t += 301
    assert b.allow() is True and b.allow() is False


# ---- budget / safety / events ----

async def test_rpm_budget_exhausted_returns_fallback():
    r, prov = make(free="ok", rpm_limit=2)
    assert (await call(r)).text == "ok"
    assert (await call(r)).text == "ok"
    res = await call(r)
    assert res.text == "FB" and res.outcome == "budget" and prov.calls["free"] == 2


async def test_disabled_router_uses_fallback():
    r, prov = make(free="ok")
    r.enabled = False
    assert (await call(r)).outcome == "off" and prov.calls["free"] == 0


async def test_safety_rejection_uses_fallback(monkeypatch):
    from navi.llm import safety

    monkeypatch.setattr(safety, "check_output", lambda text, purpose: safety.Verdict(False, ["blocklist"]))
    r, _ = make(free="bad words")
    res = await call(r)
    assert res.text == "FB" and res.outcome == "safety"


async def test_events_hook_reports_outcomes():
    events = []
    r, _ = make(free="ok")
    r.on_event = events.append
    await call(r)
    assert events[0]["outcome"] == "ok" and events[0]["purpose"] == "qa" and events[0]["provider"] == "gemini"


# ---- model check ----

def _provider_with_models(monkeypatch, listed, model=None):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    p = GeminiProvider("k", None, model)
    fake = SimpleNamespace(models=SimpleNamespace(list=lambda: [SimpleNamespace(name=f"models/{n}") for n in listed]))
    p._clients = {"free": fake}
    return p


def test_verify_model_uses_configured_when_available(monkeypatch):
    p = _provider_with_models(monkeypatch, ["my-model", "gemini-3.8-flash"], model="my-model")
    assert p.verify_model_sync()[0] == "my-model"


def test_verify_model_falls_back(monkeypatch):
    p = _provider_with_models(monkeypatch, ["gemini-3.8-flash"])
    assert p.model == "gemini-3.5-flash-lite"
    assert p.verify_model_sync()[0] == "gemini-3.8-flash"


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-env")
    assert GeminiProvider("k", None).model == "from-env"


# ---- cacheable flag ----

async def test_only_cacheable_calls_use_template_pool():
    pool = lambda cache_type, name, curse: f"cached {name}"  # noqa: E731
    r, _ = make(free=api_error(503, "UNAVAILABLE"), cache_lookup=pool, rpm_limit=1000)
    res = await r.generate(LLMRequest(purpose="qa", system="s", prompt="p"), fallback="MY FALLBACK", name="Z", cache_type="qa")
    assert res.text == "MY FALLBACK"
    res = await r.generate(LLMRequest(purpose="prediction", system="s", prompt="p"), fallback="MY FALLBACK", name="Z", cache_type="navi")
    assert res.text == "cached Z"
    res = await r.generate(LLMRequest(purpose="qa", system="s", prompt="p"), fallback="MY FALLBACK", name="Z", cacheable=True)
    assert res.text == "cached Z"
