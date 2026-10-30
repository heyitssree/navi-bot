#!/usr/bin/env bash
# Shared helpers for the operator scripts. Source this file; do not run it.
# Environment: AWS_PROFILE (default "navi"), NAVI_ENV (default "prod").
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-navi}"
NAVI_ENV="${NAVI_ENV:-prod}"
REGION="$(jq -r '.context["navi:region"]' "$(dirname "${BASH_SOURCE[0]}")/../infra/cdk.json")"
export AWS_DEFAULT_REGION="$REGION"
PREFIX="/navi/${NAVI_ENV}"

require_real_config() {
  if grep -q '<' "$(dirname "${BASH_SOURCE[0]}")/../infra/cdk.json"; then
    echo "infra/cdk.json still contains <placeholders>; fill them in first." >&2; exit 1
  fi
}

# The single bot instance (Auto Scaling group "...BotAsg..." of exactly one).
instance_id() {
  aws autoscaling describe-auto-scaling-groups \
    --query "AutoScalingGroups[?contains(AutoScalingGroupName,'BotAsg')].Instances[?LifecycleState=='InService'].InstanceId | [0][0]" \
    --output text
}

run_on_instance() {  # run_on_instance "<shell command>"
  local iid; iid="$(instance_id)"
  if [ -z "$iid" ] || [ "$iid" = "None" ]; then echo "No running bot instance found (is the Compute stack deployed?)." >&2; exit 1; fi
  aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
    --parameters "commands=[\"$1\"]" --query "Command.CommandId" --output text
}
