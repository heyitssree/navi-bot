import os
import sys
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

os.environ.setdefault("JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from navi_infra.config import NaviConfig  # noqa: E402
from navi_infra.stacks.compute_stack import ComputeStack  # noqa: E402
from navi_infra.stacks.data_stack import DataStack  # noqa: E402
from navi_infra.stacks.monitoring_stack import MonitoringStack  # noqa: E402
from navi_infra.stacks.network_stack import NetworkStack  # noqa: E402

ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def make_cfg(**kw) -> NaviConfig:
    base = dict(
        env_name="prod", account="111111111111", region="ap-south-1", instance_type="t4g.micro", use_spot=False,
        root_volume_gib=10, alert_email="owner@example.com", monthly_budget_usd=15,
        bedrock_profile_id="global.anthropic.claude-haiku-5-5", bedrock_model_arn_pattern="anthropic.claude-haiku-5-5",
        enable_partner_ingest=False, availability_zone="ap-south-1a")
    base.update(kw)
    return NaviConfig(**base)


@pytest.fixture()
def cfg():
    return make_cfg()


def build(cfg: NaviConfig):
    """All four stacks wired together exactly like app.py."""
    app = cdk.App(context={"availability-zones:account=111111111111:region=ap-south-1": ["ap-south-1a", "ap-south-1b"]})
    net = NetworkStack(app, "N", env=ENV, az=cfg.availability_zone)
    data = DataStack(app, "D", env=ENV, cfg=cfg, termination_protection=True)
    compute = ComputeStack(app, "C", env=ENV, cfg=cfg, vpc=net.vpc, bucket=data.bucket)
    mon = MonitoringStack(app, "M", env=ENV, cfg=cfg, asg=compute.asg)
    return {"net": net, "data": data, "compute": compute, "mon": mon}


@pytest.fixture(scope="session")
def stacks():
    return build(make_cfg())


@pytest.fixture(scope="session")
def templates(stacks):
    return {k: Template.from_stack(v) for k, v in stacks.items()}


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    """Tests never read the real infra/navi.env or NAVI_* variables from the shell."""
    import os

    monkeypatch.setenv("NAVI_ENV_FILE", str(tmp_path / "missing.env"))
    for name in [k for k in os.environ if k.startswith("NAVI_") and k != "NAVI_ENV_FILE"]:
        monkeypatch.delenv(name)
