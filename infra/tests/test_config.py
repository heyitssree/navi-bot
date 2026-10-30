import aws_cdk as cdk
import pytest

from navi_infra.config import ENV_NAMES, ConfigError, load_config, validate

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
    with pytest.raises(ConfigError, match="NAVI_REGION"):
        load_config(cdk.App(context=ctx))


def test_cdk_json_holds_defaults_only_and_the_example_env_file_covers_the_rest():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ctx = json.loads((root / "cdk.json").read_text())["context"]
    assert not {"navi:account", "navi:region", "navi:alertEmail"} & set(ctx)            # nothing account-specific in the repo
    example = (root / "navi.env.example").read_text()
    for name in ENV_NAMES.values():
        assert name in example or name in {"NAVI_ENABLE_PARTNER_INGEST", "NAVI_INSTANCE_TYPE", "NAVI_USE_SPOT", "NAVI_ROOT_VOLUME_GIB", "NAVI_BEDROCK_PROFILE_ID"}
    cfg = load_config(cdk.App(context=ctx), env={"NAVI_ACCOUNT": "111111111111", "NAVI_REGION": "ap-southeast-2", "NAVI_ALERT_EMAIL": "a@b.co",
                                                  "NAVI_BEDROCK_MODEL_ID": "google.gemma-3-12b-it", "NAVI_BEDROCK_MODEL_ARN_PATTERN": "google.gemma-3-12b-it"})
    assert cfg.availability_zone == "ap-southeast-2a" and not cfg.enable_partner_ingest and validate(cfg) is cfg


def test_environment_file_and_variables_override_defaults(tmp_path, monkeypatch):
    f = tmp_path / "navi.env"
    f.write_text("# comment\nNAVI_ACCOUNT=222222222222\nNAVI_REGION=\"ap-southeast-2\"\nNAVI_AVAILABILITY_ZONE=ap-southeast-2b\n")
    monkeypatch.setenv("NAVI_ENV_FILE", str(f))
    ctx = {k: v for k, v in GOOD.items() if k not in ("navi:account", "navi:region")}
    cfg = load_config(cdk.App(context=ctx))
    assert (cfg.account, cfg.region, cfg.availability_zone) == ("222222222222", "ap-southeast-2", "ap-southeast-2b")
    monkeypatch.setenv("NAVI_ACCOUNT", "333333333333")                      # the shell wins over the file
    assert load_config(cdk.App(context=ctx)).account == "333333333333"
