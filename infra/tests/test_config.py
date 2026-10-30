import aws_cdk as cdk
import pytest

from navi_infra.config import ConfigError, load_config, validate

GOOD = {
    "navi:envName": "prod", "navi:account": "111111111111", "navi:region": "ap-south-1", "navi:instanceType": "t4g.micro",
    "navi:useSpot": False, "navi:rootVolumeGiB": 10, "navi:alertEmail": "a@b.co", "navi:monthlyBudgetUsd": 15,
    "navi:bedrockProfileId": "global.anthropic.claude-haiku-5-5", "navi:bedrockModelArnPattern": "anthropic.claude-haiku-5-5",
    "navi:enablePartnerIngest": False,
}


def test_loads_from_context():
    cfg = load_config(cdk.App(context=GOOD))
    assert (cfg.env_name, cfg.region, cfg.monthly_budget_usd, cfg.use_spot, cfg.availability_zone) == ("prod", "ap-south-1", 15, False, "ap-south-1a")
    assert cfg.name("bot") == "navi-prod-bot" and cfg.ssm_prefix == "/navi/prod"


def test_string_flags_from_the_command_line_are_understood():
    cfg = load_config(cdk.App(context={**GOOD, "navi:useSpot": "true", "navi:enablePartnerIngest": "false"}))
    assert cfg.use_spot is True and cfg.enable_partner_ingest is False


@pytest.mark.parametrize("key,value,fragment", [
    ("navi:account", "12345", "12-digit"),
    ("navi:account", "<12-digit account id>", "placeholder"),
    ("navi:alertEmail", "<owner email>", "placeholder"),
    ("navi:alertEmail", "not-an-email", "email"),
    ("navi:bedrockProfileId", "<from: aws bedrock list-inference-profiles>", "placeholder"),
    ("navi:envName", "Prod Env", "lower-case"),
    ("navi:monthlyBudgetUsd", 0, "positive"),
    ("navi:rootVolumeGiB", 4, "positive"),
])
def test_bad_values_stop_the_deploy(key, value, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config(cdk.App(context={**GOOD, key: value}))


def test_missing_key_is_reported():
    ctx = dict(GOOD)
    del ctx["navi:region"]
    with pytest.raises(ConfigError, match="navi:region"):
        load_config(cdk.App(context=ctx))


def test_real_cdk_json_is_complete_and_valid():
    import json
    from pathlib import Path

    ctx = json.loads((Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]
    cfg = load_config(cdk.App(context=ctx))
    assert cfg.bedrock_profile_id.startswith("global.anthropic.claude-haiku") and not cfg.enable_partner_ingest
    assert validate(cfg) is cfg
