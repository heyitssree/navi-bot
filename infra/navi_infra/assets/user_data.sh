#!/bin/bash
# Instance bootstrap (EC2 user data). Upper-case double-underscore placeholders are filled by navi_infra.userdata.
# No credentials live here: tokens are read from SSM Parameter Store by the app at startup.
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker

# 1 GiB swap: headroom for discord.py + matplotlib on a 1 GiB instance
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /opt/navi /var/lib/navi
chown 10001:10001 /var/lib/navi        # the container runs as uid 10001

cat > /opt/navi/env <<'ENV'
AWS_REGION=__REGION__
AWS_DEFAULT_REGION=__REGION__
NAVI_ENV=__ENV__
NAVI_SSM_PREFIX=/navi/__ENV__
NAVI_BUCKET=__BUCKET__
BEDROCK_MODEL_ID=__BEDROCK_MODEL_ID__
LOG_GROUP=__LOG_GROUP__
IMAGE_PARAM=__IMAGE_PARAM__
DB_PATH=/app/data/navi.db
PRIVACY_DB_PATH=/app/data/privacy.db
LITESTREAM_ENABLED=1
LOG_TO_FILE=0
ENV
chmod 600 /opt/navi/env

cat > /opt/navi/update.sh <<'UPDATE'
__UPDATE_SH__
UPDATE
chmod 755 /opt/navi/update.sh

cat > /etc/systemd/system/navi.service <<'UNIT'
__NAVI_SERVICE__
UNIT

systemctl daemon-reload
systemctl enable --now navi
