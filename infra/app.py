#!/usr/bin/env python3
"""CDK entry point for the Navi bot.

    cdk synth                         # uses navi:* context from cdk.json
    cdk deploy --all --require-approval broadening
"""
import aws_cdk as cdk

from navi_infra.config import load_config
from navi_infra.stacks.compute_stack import ComputeStack
from navi_infra.stacks.data_stack import DataStack
from navi_infra.stacks.monitoring_stack import MonitoringStack
from navi_infra.stacks.network_stack import NetworkStack

app = cdk.App()
cfg = load_config(app)
env = cdk.Environment(account=cfg.account, region=cfg.region)
prefix = f"Navi-{cfg.env_name}"

net = NetworkStack(app, f"{prefix}-Network", env=env, az=cfg.availability_zone, description=f"Navi network ({cfg.env_name})")
data = DataStack(app, f"{prefix}-Data", env=env, cfg=cfg, description=f"Navi data bucket ({cfg.env_name})",
                 termination_protection=True)
compute = ComputeStack(app, f"{prefix}-Compute", env=env, cfg=cfg, vpc=net.vpc, bucket=data.bucket,
                       description=f"Navi bot instance ({cfg.env_name})")
MonitoringStack(app, f"{prefix}-Monitoring", env=env, cfg=cfg, asg=compute.asg,
                description=f"Navi alarms and budget ({cfg.env_name})")

if cfg.enable_partner_ingest:
    raise SystemExit("navi:enablePartnerIngest is true but the partner ingest stack (Phase 8b) is not built; "
                     "see infra/README.md")

cdk.Tags.of(app).add("project", "navi-bot")
cdk.Tags.of(app).add("env", cfg.env_name)

app.synth()
