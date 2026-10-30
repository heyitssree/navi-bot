# Navi on AWS (Phase 8)

CDK (Python) stacks for one small, cheap, single-instance deployment in `ap-south-1`.

| Stack | What it holds |
|---|---|
| `Navi-<env>-Network` | VPC 10.40.0.0/24, one public subnet, no NAT, S3 gateway endpoint |
| `Navi-<env>-Data` | private S3 bucket (Litestream replicas, `media/`, `seed/`, `exports/`), termination protection, RETAIN |
| `Navi-<env>-Compute` | Docker image asset, SSM parameters, IAM role (SSM, S3, ECR, logs, Bedrock), launch template, ASG of exactly one Graviton instance |
| `Navi-<env>-Monitoring` | SNS email topic, heartbeat alarm, monthly budget alerts |

Secrets are never in CDK or in chat. They live in SSM Parameter Store (`/navi/<env>/...`) and are entered only through `scripts/put-secrets.sh`.

## Configure

Edit the `navi:*` values in `cdk.json` (account, region, alert email, budget, instance type). Synth refuses `<placeholder>` values.
`enablePartnerIngest` must stay `false`: Phase 8b (partner ingest) is not built.

## Develop (no AWS calls)

```bash
cd infra
make setup     # venv + deps
make ci        # lint (cfn-lint) + tests + synth
```

## First-time deploy (each step costs money or changes the account; run them yourself)

```bash
export AWS_PROFILE=navi
cd infra
make bootstrap                      # cdk bootstrap, once per account/region
make diff                           # review before deploying
cd .. && scripts/put-secrets.sh     # prompts for Discord token + Gemini keys; sets run_enabled=false
scripts/put-config.sh               # owner id, guild id, channels (not secret)
scripts/deploy.sh                   # cdk deploy; instance starts idle because run_enabled=false
```

Then confirm the SNS subscription email. At cutover (Phase 9): migrate the DB with `tools/migrate_v2.py`, `python -m tools.media_to_s3 --db data/v2/navi.db --bucket <bucket>`,
`scripts/seed-db.sh`, rotate the Discord token, then `scripts/enable.sh`. `scripts/disable.sh` stops the bot without destroying anything.

## Notes

- Heartbeat: the bot publishes `Navi/Heartbeat` every 5 minutes; the alarm fires when it is missing for 15 minutes.
- The bot restores its databases from S3 on a fresh instance (Litestream, 72 h retention) and falls back to `s3://<bucket>/seed/`.
- Budget amounts are USD; confirm the unit if your account is billed through AISPL.
