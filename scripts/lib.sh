#!/usr/bin/env bash
# Shared helpers for the operator scripts. Source this file; do not run it.
# Environment: AWS_PROFILE (default "navi"), NAVI_ENV (default "prod").
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-navi}"
NAVI_ENV="${NAVI_ENV:-prod}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Account, region and the rest come from infra/navi.env (git-ignored); real environment variables win over the file.
ENV_FILE="${NAVI_ENV_FILE:-$ROOT_DIR/infra/navi.env}"
if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    v="${v%%#*}"; v="$(echo "$v" | sed -e 's/^[[:space:]"]*//' -e 's/[[:space:]"]*$//')"
    [ -z "${!k:-}" ] && export "$k=$v"
  done < "$ENV_FILE"
fi
REGION="${NAVI_REGION:-}"
export AWS_DEFAULT_REGION="$REGION"
PREFIX="/navi/${NAVI_ENV}"

require_real_config() {
  if [ -z "${NAVI_ACCOUNT:-}" ] || [ -z "$REGION" ] || [[ "$NAVI_ACCOUNT$REGION" == *"<"* ]]; then
    echo "NAVI_ACCOUNT / NAVI_REGION are not set. Copy infra/navi.env.example to infra/navi.env and fill it in." >&2; exit 1
  fi
  local actual; actual="$(aws sts get-caller-identity --query Account --output text)"
  if [ "$actual" != "$NAVI_ACCOUNT" ]; then
    echo "The CLI profile '$AWS_PROFILE' is account $actual but infra/navi.env says $NAVI_ACCOUNT. Aborting." >&2; exit 1
  fi
}

# The single bot instance (Auto Scaling group "...BotAsg..." of exactly one).
instance_id() {
  aws autoscaling describe-auto-scaling-groups \
    --query "AutoScalingGroups[?contains(AutoScalingGroupName,'BotAsg')] | [0].Instances[?LifecycleState=='InService'] | [0].InstanceId" \
    --output text
}

run_on_instance() {  # run_on_instance "<shell command>"
  local iid; iid="$(instance_id)"
  if [ -z "$iid" ] || [ "$iid" = "None" ]; then echo "No running bot instance found (is the Compute stack deployed?)." >&2; exit 1; fi
  aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
    --parameters "commands=[\"$1\"]" --query "Command.CommandId" --output text
}
