"""Bedrock provider (botocore Stubber), multi-provider routing, fallback chain and settings."""
import json

import boto3
import pytest
from botocore.config import Config
from botocore.stub import Stubber

from navi.config import Config as AppConfig
from navi.llm.base import LLMError, LLMRequest
from navi.llm.bedrock import BedrockProvider, classify_client_error
from navi.llm.factory import build_providers
from navi.llm.router import LLMRouter
from navi.settings.store import Settings
from tests.legacy.harness import make_config
from tests.phase1.test_llm_router import Clock, FakeProvider, api_error

MODEL = "global.anthropic.claude-haiku-5-5"
REQ = LLMRequest(purpose="qa", system="SYS", prompt="hello", max_tokens=77, temperature=0.3)


def runtime_client():
    return boto3.client("bedrock-runtime", region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="y",
                        config=Config(retries={"max_attempts": 1}))


def converse_ok(text="Hi there", tin=11, tout=4):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn",
            "usage": {"inputTokens": tin, "outputTokens": tout, "totalTokens": tin + tout}, "metrics": {"latencyMs": 123}}


@pytest.fixture()
def stubbed():
    client = runtime_client()
    with Stubber(client) as stub:
        yield BedrockProvider(MODEL, "ap-south-1", client=client), stub


async def test_success_sends_the_converse_request_and_reads_tokens(stubbed):
    provider, stub = stubbed
    stub.add_response("converse", converse_ok(), expected_params={
        "modelId": MODEL, "system": [{"text": "SYS"}], "messages": [{"role": "user", "content": [{"text": "hello"}]}],
        "inferenceConfig": {"maxTokens": 77, "temperature": 0.3}})
    resp = await provider.generate(REQ)
    assert (resp.text, resp.input_tokens, resp.output_tokens, resp.provider, resp.model) == ("Hi there", 11, 4, "bedrock", MODEL)
    assert resp.latency_ms >= 0
    stub.assert_no_pending_responses()


async def test_multiple_text_blocks_are_joined(stubbed):
    provider, stub = stubbed
    out = converse_ok(); out["output"]["message"]["content"] = [{"text": "Hello "}, {"text": "world "}]
    stub.add_response("converse", out)
    assert (await provider.generate(REQ)).text == "Hello world"


@pytest.mark.parametrize("code,status,kind,retry", [
    ("ThrottlingException", 429, "rate_limited", 10.0),
    ("TooManyRequestsException", 429, "rate_limited", 10.0),
    ("ServiceQuotaExceededException", 400, "rate_limited", 10.0),
    ("AccessDeniedException", 403, "config", None),
    ("ValidationException", 400, "config", None),
    ("ResourceNotFoundException", 404, "config", None),
    ("ModelTimeoutException", 408, "server", None),
    ("InternalServerException", 500, "server", None),
    ("ServiceUnavailableException", 503, "server", None),
])
async def test_error_classification(stubbed, code, status, kind, retry):
    provider, stub = stubbed
    stub.add_client_error("converse", service_error_code=code, service_message="boom", http_status_code=status)
    with pytest.raises(LLMError) as exc:
        await provider.generate(REQ)
    assert (exc.value.kind, exc.value.retry_after) == (kind, retry) and code in str(exc.value)


def test_non_client_errors_are_server_errors():
    from botocore.exceptions import EndpointConnectionError, ReadTimeoutError

    assert classify_client_error(EndpointConnectionError(endpoint_url="https://x")).kind == "server"
    assert classify_client_error(ReadTimeoutError(endpoint_url="https://x")).kind == "server"
    assert classify_client_error(RuntimeError("weird")).kind == "server"


def test_a_model_id_is_required_and_never_hardcoded():
    with pytest.raises(ValueError, match="BEDROCK_MODEL_ID"):
        BedrockProvider("")
    from pathlib import Path

    assert "claude-haiku" not in Path("navi/llm/bedrock.py").read_text().replace("Claude Haiku 5.5", "")


def test_verify_model_checks_the_inference_profile():
    control = boto3.client("bedrock", region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="y")
    provider = BedrockProvider(MODEL, "ap-south-1", client=runtime_client(), control_client=control)
    with Stubber(control) as stub:
        stub.add_response("get_inference_profile", {
            "inferenceProfileName": "Global Claude Haiku 5.5", "models": [{"modelArn": "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-haiku-5-5"}], "inferenceProfileArn": "arn:aws:bedrock:ap-south-1:1:inference-profile/x",
            "inferenceProfileId": MODEL, "status": "ACTIVE", "type": "SYSTEM_DEFINED"}, {"inferenceProfileIdentifier": MODEL})
        assert provider.verify_model_sync() == (MODEL, None)
        stub.add_client_error("get_inference_profile", service_error_code="ResourceNotFoundException", http_status_code=404)
        model, err = provider.verify_model_sync()
        assert err.kind == "config"
        stub.add_client_error("get_inference_profile", service_error_code="AccessDeniedException", http_status_code=403)
        assert provider.verify_model_sync()[1].kind == "server"          # missing GetInferenceProfile permission: warn, don't alarm


GEMMA = "google.gemma-3-12b-it"


async def test_a_model_without_system_prompt_support_gets_the_instructions_in_the_user_message():
    client = runtime_client()
    with Stubber(client) as stub:
        provider = BedrockProvider(GEMMA, "ap-south-1", client=client)
        stub.add_client_error("converse", service_error_code="ValidationException", http_status_code=400,
                              service_message="This model doesn't support system messages.")
        stub.add_response("converse", converse_ok("Hello"), expected_params={
            "modelId": GEMMA, "messages": [{"role": "user", "content": [{"text": "SYS\n\nhello"}]}],
            "inferenceConfig": {"maxTokens": 77, "temperature": 0.3}})
        assert (await provider.generate(REQ)).text == "Hello"
        stub.add_response("converse", converse_ok("Again"), expected_params={        # remembered: no second failed attempt
            "modelId": GEMMA, "messages": [{"role": "user", "content": [{"text": "SYS\n\nhello"}]}],
            "inferenceConfig": {"maxTokens": 77, "temperature": 0.3}})
        assert (await provider.generate(REQ)).text == "Again"
        stub.assert_no_pending_responses()


async def test_other_validation_errors_are_not_retried_without_the_system_prompt():
    client = runtime_client()
    with Stubber(client) as stub:
        provider = BedrockProvider(GEMMA, "ap-south-1", client=client)
        stub.add_client_error("converse", service_error_code="ValidationException", http_status_code=400, service_message="bad model id")
        with pytest.raises(LLMError) as e:
            await provider.generate(REQ)
        assert e.value.kind == "config" and provider._system_supported is True


def test_plain_on_demand_models_skip_the_inference_profile_check():
    provider = BedrockProvider(GEMMA, "ap-south-1", client=runtime_client())        # no control client: must not be touched
    assert provider.verify_model_sync() == (GEMMA, None)


# ------------------------------------------------------------------------------ router behaviour is unchanged

async def test_router_treats_bedrock_errors_like_gemini_errors():
    clock = Clock()
    client = runtime_client()
    provider = BedrockProvider(MODEL, "ap-south-1", client=client)
    router = LLMRouter(provider, clock=clock, rpm_limit=1000)
    alerts = []
    router.on_config_error = alerts.append
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code="ThrottlingException", http_status_code=429)
        res = await router.generate(REQ, fallback="FB")
        assert res.text == "FB" and router.breaker.failures == 0            # throttling: key cools down, breaker untouched
        assert (await router.generate(REQ, fallback="FB")).outcome == "cooldown"          # cooling down for 10 s
        clock.t += 11
        stub.add_response("converse", converse_ok("fine"))
        assert (await router.generate(REQ, fallback="FB")).text == "fine"
        stub.add_client_error("converse", service_error_code="AccessDeniedException", http_status_code=403)
        assert (await router.generate(REQ, fallback="FB")).outcome == "error"
        assert router.is_circuit_open and len(alerts) == 1 and "bedrock config error" in alerts[0]
        clock.t += 301
        for _ in range(3):
            stub.add_client_error("converse", service_error_code="InternalServerException", http_status_code=500)
        for _ in range(3):
            await router.generate(REQ, fallback="FB")
            clock.t += 1
        assert router.is_circuit_open


# ------------------------------------------------------------------------------ several providers

class Named(FakeProvider):
    def __init__(self, name, *a, **k):
        super().__init__(*a, **k)
        self.name = name
        self.model = f"{name}-model"


def make_router(gemini="gem", bedrock="bed", **kw):
    settings = Settings()
    router = LLMRouter(Named("gemini", gemini, paid=None), settings=settings, clock=Clock(), rpm_limit=1000)
    router.add_provider(Named("bedrock", bedrock))
    return router, settings


async def test_ai_provider_setting_picks_which_provider_answers():
    router, settings = make_router()
    assert (await router.generate(REQ, fallback="FB")).text == "gem"
    settings.set("ai.provider", "bedrock")
    res = await router.generate(REQ, fallback="FB")
    assert (res.text, res.provider, router.model) == ("bed", "bedrock", "bedrock-model")
    settings.set("ai.provider", "off")
    assert (await router.generate(REQ, fallback="FB")).outcome == "off"


async def test_provider_that_is_not_configured_degrades_to_fallbacks_without_crashing():
    settings = Settings()
    router = LLMRouter(Named("gemini", "gem"), settings=settings, clock=Clock())
    settings.set("ai.provider", "bedrock")
    res = await router.generate(REQ, fallback="FB")
    assert (res.text, res.outcome) == ("FB", "off")


async def test_fallback_provider_takes_over_when_the_active_one_fails():
    router, settings = make_router(bedrock=api_error(503, "UNAVAILABLE"))
    settings.set("ai.provider", "bedrock")
    assert (await router.generate(REQ, fallback="FB")).text == "FB"                       # no fallback configured (default off)
    settings.set("ai.fallback_provider", "gemini")
    res = await router.generate(REQ, fallback="FB")
    assert (res.text, res.provider) == ("gem", "gemini")
    assert router.breaker_for("bedrock").failures >= 1 and router.breaker_for("gemini").failures == 0


async def test_fallback_kicks_in_for_config_errors_and_open_breakers_but_counts_one_budget_unit():
    router, settings = make_router(bedrock=api_error(403, "PERMISSION_DENIED"))
    settings.set("ai.provider", "bedrock"); settings.set("ai.fallback_provider", "gemini")
    before = router.daily_calls
    assert (await router.generate(REQ, fallback="FB")).text == "gem"
    assert router.breaker_for("bedrock").is_open and router.daily_calls == before + 1
    res = await router.generate(REQ, fallback="FB")                                       # bedrock breaker open: straight to gemini
    assert res.text == "gem" and router._providers["bedrock"].calls["free"] == 1


async def test_fallback_is_not_used_for_budget_limits_or_safety_rejections(blocked):
    router, settings = make_router(bedrock="a zorgblat reply")
    settings.set("ai.provider", "bedrock"); settings.set("ai.fallback_provider", "gemini")
    res = await router.generate(REQ, fallback="FB")
    assert (res.text, res.outcome) == ("FB", "safety")                                    # unsafe text is replaced, not retried elsewhere
    assert router._providers["gemini"].calls["free"] == 0
    settings.set("ai.rpm_budget", 1)
    router._request_count = 1
    assert (await router.generate(REQ, fallback="FB")).outcome == "budget"


async def test_each_provider_has_its_own_breaker_and_status_lists_them():
    router, settings = make_router(bedrock=api_error(500, "INTERNAL"))
    settings.set("ai.provider", "bedrock")
    for _ in range(3):
        await router.generate(REQ, fallback="FB")
    info = router.status_dict()
    assert info["breakers"] == {"gemini": "closed", "bedrock": "open"} and info["providers"] == ["bedrock", "gemini"]
    assert info["circuit_open"] is True                                                  # the active provider's breaker
    settings.set("ai.provider", "gemini")
    assert router.status_dict()["circuit_open"] is False


async def test_ai_model_override_applies_to_gemini_only():
    router, settings = make_router()
    settings.set("ai.model", "custom-gemini")
    settings.set("ai.provider", "bedrock")
    await router.generate(REQ, fallback="FB")
    assert router._providers["gemini"].model == "gemini-model" and router._providers["bedrock"].model == "bedrock-model"
    settings.set("ai.provider", "gemini")
    await router.generate(REQ, fallback="FB")
    assert router._providers["gemini"].model == "custom-gemini"


# ------------------------------------------------------------------------------ configuration

def cfg(**kw):
    base = make_config(**kw).__dict__.copy()
    base.update(kw)
    return AppConfig(**base)


def test_build_providers_from_credentials_and_model_id(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    assert [p.name for p in build_providers(cfg(free_api_key="k"))] == ["gemini"]
    both = build_providers(cfg(free_api_key="k", bedrock_model_id=MODEL, aws_region="ap-south-1"))
    assert [p.name for p in both] == ["gemini", "bedrock"] and both[1].model == MODEL and both[1].region == "ap-south-1"
    only = build_providers(cfg(bedrock_model_id=MODEL))
    assert [p.name for p in only] == ["bedrock"]
    with pytest.raises(ValueError):
        build_providers(cfg())


def test_setting_overrides_the_environment_model_id(db, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    settings = Settings(); settings.bind(db)
    settings.set("ai.bedrock_model_id", "global.anthropic.claude-haiku-5-5-custom")
    p = build_providers(cfg(bedrock_model_id="from-env"), settings)
    assert p[0].model == "global.anthropic.claude-haiku-5-5-custom"


def test_config_reads_bedrock_environment(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODEL); monkeypatch.setenv("AWS_REGION", "us-east-1")
    c = AppConfig.from_env()
    assert (c.bedrock_model_id, c.aws_region) == (MODEL, "us-east-1")
    monkeypatch.delenv("BEDROCK_MODEL_ID"); monkeypatch.delenv("AWS_REGION")
    c = AppConfig.from_env()
    assert (c.bedrock_model_id, c.aws_region) == (None, "ap-south-1")


# ------------------------------------------------------------------------------ cost estimate and status

def test_cost_estimate_uses_the_prices_from_settings(db):
    from navi.db.repos.events import estimate_cost, log_llm_call, llm_usage_by_provider_today

    log_llm_call(db, "bedrock", MODEL, "qa", "ok", 1_000_000, 200_000, 50)
    log_llm_call(db, "bedrock", MODEL, "qa", "ok", 1_000_000, 0, 50)
    log_llm_call(db, "gemini", "g", "qa", "ok", 5, 5, 5)
    log_llm_call(db, "bedrock", MODEL, "qa", "budget", 0, 0, 0)               # not a provider call
    usage = llm_usage_by_provider_today(db)
    assert usage["bedrock"] == (2, 2_000_000, 200_000) and usage["gemini"] == (1, 5, 5)
    assert estimate_cost(*usage["bedrock"][1:], 0.10, 0.50) == pytest.approx(0.30)
    assert estimate_cost(*usage["bedrock"][1:], 1.0, 2.0) == pytest.approx(2.4)


async def test_status_shows_providers_and_estimated_cost(db, tmp_path, monkeypatch):
    from navi.cogs import admin
    from navi.cogs.admin import AdminGroup
    from navi.db.repos.events import log_llm_call
    from tests.legacy.harness import make_ctx
    from tests.phase4.test_admin_commands import interaction, run

    ctx = make_ctx(db, owner_id=1)
    ctx.llm = LLMRouter(Named("gemini", "x"), settings=ctx.settings)
    ctx.llm.add_provider(Named("bedrock", "y"))
    log_llm_call(db, "bedrock", MODEL, "qa", "ok", 1_000_000, 1_000_000, 10)
    monkeypatch.setattr(admin, "DB_PATH", tmp_path / "x.db")
    i = await run(AdminGroup.status, ctx=ctx)
    text = " ".join(f"{f.name} {f.value}" for f in i.followup.send.await_args.kwargs["embed"].fields)
    assert "Configured: bedrock, gemini" in text and "$0.6000" in text and "bedrock: 1 calls" in text


async def test_setting_an_unconfigured_provider_warns_the_admin(db):
    from navi.cogs.admin import AdminGroup
    from tests.legacy.harness import make_ctx
    from tests.phase4.test_admin_commands import reply, run

    ctx = make_ctx(db, owner_id=1)
    ctx.llm = LLMRouter(Named("gemini", "x"), settings=ctx.settings)
    i = await run(AdminGroup.set_cmd, "ai.provider", "bedrock", ctx=ctx)
    assert "not configured on this server" in reply(i)[0]
    ctx.llm.add_provider(Named("bedrock", "y"))
    assert "not configured" not in reply(await run(AdminGroup.set_cmd, "ai.provider", "bedrock", ctx=ctx))[0]
