#!/bin/bash
# /opt/navi/update.sh   pull | run | deploy
# Reads the image uri and the run switch from SSM Parameter Store; no credentials are stored on the instance.
set -euo pipefail
source /opt/navi/env
ssm() { aws ssm get-parameter --name "$1" --query Parameter.Value --output text 2>/dev/null || echo "${2:-}"; }
IMAGE=$(ssm "$IMAGE_PARAM")
REGISTRY=${IMAGE%%/*}
case "${1:-}" in
  pull)
    aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
    docker pull "$IMAGE" ;;
  run)
    if [ "$(ssm "$NAVI_SSM_PREFIX/run_enabled" false)" != "true" ]; then
      echo "run_enabled != true; idling"; exec sleep infinity; fi
    docker rm -f navi 2>/dev/null || true
    exec docker run --name navi --rm --env-file /opt/navi/env \
      -v /var/lib/navi:/app/data \
      --log-driver=awslogs --log-opt awslogs-group="$LOG_GROUP" \
      --log-opt awslogs-region="$AWS_REGION" "$IMAGE" ;;
  deploy)
    "$0" pull && systemctl restart navi ;;
  *) echo "usage: $0 pull|run|deploy"; exit 2 ;;
esac
