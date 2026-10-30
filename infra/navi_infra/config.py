"""Typed configuration for the Navi stacks, read from the `navi:*` context keys in cdk.json.

Override any value for one run with `cdk synth -c navi:envName=dev`. Values still in <angle brackets> are
placeholders and make load_config() refuse to continue, so a deploy can never go out half-configured.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NaviConfig:
    env_name: str
    account: str
    region: str
    instance_type: str
    use_spot: bool
    root_volume_gib: int
    alert_email: str
    monthly_budget_usd: int
    bedrock_profile_id: str          # the id the app calls: an inference profile (global.anthropic.claude-haiku-5-5) or a plain model id (google.gemma-3-12b-it)
    bedrock_model_arn_pattern: str   # foundation model id (the profile routes to it, or the model itself), e.g. google.gemma-3-12b-it
    enable_partner_ingest: bool
    availability_zone: str = ""        # explicit, so synth needs no AWS lookup (default <region>a)

    def name(self, suffix: str) -> str:
        """Consistent physical-name prefix, e.g. navi-prod-bot."""
        return f"navi-{self.env_name}-{suffix}"

    @property
    def bedrock_uses_profile(self) -> bool:
        """Cross-Region profile ids start with a geography (global., apac., in., us., eu. ...); plain on-demand model ids do not."""
        return self.bedrock_profile_id.split(".", 1)[0] in {"global", "apac", "in", "us", "eu", "jp", "au", "ca", "us-gov"}

    @property
    def ssm_prefix(self) -> str:
        return f"/navi/{self.env_name}"


class ConfigError(ValueError):
    pass


def _ctx(app, key: str):
    value = app.node.try_get_context(f"navi:{key}")
    if value is None:
        raise ConfigError(f"Missing context value navi:{key} in cdk.json")
    return value


def _flag(value) -> bool:
    return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")


def validate(cfg: NaviConfig) -> NaviConfig:
    for field_name in ("account", "alert_email", "bedrock_profile_id", "bedrock_model_arn_pattern"):
        if "<" in getattr(cfg, field_name):
            raise ConfigError(f"navi:{field_name} is still a placeholder: {getattr(cfg, field_name)!r}")
    if not re.fullmatch(r"\d{12}", cfg.account):
        raise ConfigError("navi:account must be a 12-digit AWS account id")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cfg.alert_email):
        raise ConfigError("navi:alertEmail must be an email address")
    if not re.fullmatch(r"[a-z0-9-]{2,20}", cfg.env_name):
        raise ConfigError("navi:envName must be lower-case letters, digits and dashes")
    if cfg.monthly_budget_usd <= 0 or cfg.root_volume_gib < 8:
        raise ConfigError("navi:monthlyBudgetUsd must be positive and navi:rootVolumeGiB at least 8")
    return cfg


def load_config(app) -> NaviConfig:
    return validate(NaviConfig(
        env_name=str(_ctx(app, "envName")),
        account=str(_ctx(app, "account")),
        region=str(_ctx(app, "region")),
        instance_type=str(_ctx(app, "instanceType")),
        use_spot=_flag(_ctx(app, "useSpot")),
        root_volume_gib=int(_ctx(app, "rootVolumeGiB")),
        alert_email=str(_ctx(app, "alertEmail")),
        monthly_budget_usd=int(_ctx(app, "monthlyBudgetUsd")),
        bedrock_profile_id=str(_ctx(app, "bedrockProfileId")),
        bedrock_model_arn_pattern=str(_ctx(app, "bedrockModelArnPattern")),
        enable_partner_ingest=_flag(_ctx(app, "enablePartnerIngest")),
        availability_zone=str(app.node.try_get_context("navi:availabilityZone") or f"{_ctx(app, 'region')}a"),
    ))
