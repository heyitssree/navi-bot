"""Phase 1: error classes, per-key cooldowns, circuit breaker, owner alerts, model check."""
from types import SimpleNamespace

import pytest
from google.genai import errors

from services.api_manager import ApiManager
from services.gemini_service import CircuitBreaker, GeminiService, classify_error


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def api_error(code, status=None, message="boom", details=None):
    body = {"error": {"code": code, "status": status, "message": message, "details": details or []}}
    return errors.APIError(code, body)


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour, self.calls, self.listed = behaviour, 0, []

    def generate_content(self, **kw):
        self.calls += 1
        out = self.behaviour() if callable(self.behaviour) else self.behaviour
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(text=out)

    def list(self):
        return [SimpleNamespace(name=f"models/{n}") for n in self.listed]


def make(free=None, paid=None, clock=None, db=None):
    svc = GeminiService("k1" if free is not None else None, "k2" if paid is not None else None, db, clock=clock or Clock())
    if free is not None:
        svc._free_client = SimpleNamespace(models=free)
    if paid is not None:
        svc._paid_client = SimpleNamespace(models=paid)
    return svc


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

def test_429_short_cooldown_not_breaker():
    clk = Clock()
    m = FakeModels(api_error(429, "RESOURCE_EXHAUSTED", message="retry in 10s"))
    svc = make(free=m, clock=clk)
    for _ in range(10):
        assert svc.call("p", "s") is None
        clk.t += 1
    assert svc.breaker.failures == 0 and not svc.is_circuit_open
    assert m.calls == 1  # key is cooling down; no hammering
    clk.t += 10  # cooldown over -> key is tried again
    svc.call("p", "s")
    assert m.calls == 2


def test_429_on_free_falls_through_to_paid():
    free = FakeModels(api_error(429, "RESOURCE_EXHAUSTED"))
    paid = FakeModels("hello")
    svc = make(free=free, paid=paid)
    assert svc.call("p", "s") == "hello"
    assert svc.active_key == "paid"


# ---- config errors ----

def test_404_opens_breaker_and_alerts_owner_once():
    clk = Clock()
    m = FakeModels(api_error(404, "NOT_FOUND", message="model not found"))
    svc = make(free=m, clock=clk)
    alerts = []
    svc.on_config_error = alerts.append
    assert svc.call("p", "s") is None
    assert svc.is_circuit_open and len(alerts) == 1
    assert "model not found" in alerts[0]
    clk.t += 301  # breaker half-opens; probe fails again with config error
    svc.call("p", "s")
    clk.t += 301
    svc.call("p", "s")
    assert len(alerts) == 1  # within the hour: still a single DM
    clk.t += 3600
    svc.call("p", "s")
    assert len(alerts) == 2


# ---- server errors / breaker ----

def test_three_server_errors_open_five_minutes_then_probe():
    clk = Clock()
    state = {"fail": True}
    m = FakeModels(lambda: api_error(503, "UNAVAILABLE") if state["fail"] else "ok")
    svc = make(free=m, clock=clk)
    svc.call("p", "s"); svc.call("p", "s")
    assert not svc.is_circuit_open
    svc.call("p", "s")
    assert svc.is_circuit_open
    calls = m.calls
    assert svc.call("p", "s") is None and m.calls == calls  # open: provider untouched
    clk.t += 299
    assert svc.is_circuit_open
    clk.t += 2
    assert not svc.is_circuit_open
    state["fail"] = False
    assert svc.call("p", "s") == "ok"  # half-open probe succeeds -> closed
    assert svc.breaker.failures == 0 and not svc.is_circuit_open


def test_failed_probe_reopens():
    clk = Clock()
    svc = make(free=FakeModels(api_error(500, "INTERNAL")), clock=clk)
    for _ in range(3):
        svc.call("p", "s")
    clk.t += 301
    svc.call("p", "s")  # probe fails
    assert svc.is_circuit_open


def test_success_resets_failure_streak():
    state = {"n": 0}

    def beh():
        state["n"] += 1
        return "ok" if state["n"] == 3 else api_error(503, "UNAVAILABLE")

    svc = make(free=FakeModels(beh))
    svc.call("p", "s"); svc.call("p", "s"); svc.call("p", "s")
    svc.call("p", "s"); svc.call("p", "s")
    assert not svc.is_circuit_open


def test_breaker_single_probe_only():
    clk = Clock()
    b = CircuitBreaker(clock=clk)
    b.trip()
    clk.t += 301
    assert b.allow() is True and b.allow() is False


# ---- model check ----

def test_verify_model_uses_configured_when_available(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "my-model")
    m = FakeModels("x"); m.listed = ["my-model", "gemini-3.8-flash"]
    svc = make(free=m)
    assert svc.verify_model() == "my-model"


def test_verify_model_falls_back():
    m = FakeModels("x"); m.listed = ["gemini-3.8-flash"]
    svc = make(free=m)
    assert svc.model == "gemini-3.5-flash-lite"
    assert svc.verify_model() == "gemini-3.8-flash"


def test_default_model_without_env(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert make(free=FakeModels("x")).model == "gemini-3.5-flash-lite"


# ---- cacheable flag ----

def test_only_cacheable_calls_use_template_pool(db):
    for i in range(25):
        db.execute("INSERT INTO predictions_cache (cache_type, template_text) VALUES ('qa', ?)", [f"cached {i} {{user}}"])
    db.commit()
    svc = make(free=FakeModels(api_error(503, "UNAVAILABLE")), db=db)
    mgr = ApiManager(svc, db)
    text, _ = mgr.call("p", "s", cache_type="qa", name="Z", fallback_message="MY FALLBACK")
    assert text == "MY FALLBACK"
    text, _ = mgr.call("p", "s", cache_type="qa", name="Z", fallback_message="MY FALLBACK", cacheable=True)
    assert text.startswith("cached")
