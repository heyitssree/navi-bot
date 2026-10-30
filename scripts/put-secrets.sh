#!/usr/bin/env bash
# Store the bot's secrets in SSM Parameter Store (SecureString) under /navi/<env>/.
# Values are typed at a hidden prompt (never echoed, never written to a file, never in shell history) and sent to AWS
# by boto3 (scripts/put_secret.py), so they do not appear in the process list. Blank = skip that value. Run it yourself; do not paste
# secrets into chat.
source "$(dirname "$0")/lib.sh"
require_real_config

# Default: only the Discord token. Pass extra names to store more, e.g. scripts/put-secrets.sh discord_token gemini_api_key_free
PY="$ROOT_DIR/.venv/bin/python"; [ -x "$PY" ] || PY=python3
for name in ${@:-discord_token}; do
  "$PY" "$ROOT_DIR/scripts/put_secret.py" "${PREFIX}/${name}"
done
# The bot stays idle until you flip this (scripts/enable.sh). Created only if missing, so re-running never switches a live bot off.
aws ssm put-parameter --name "${PREFIX}/run_enabled" --type String --value false --no-overwrite >/dev/null 2>&1 || true
echo "  ${PREFIX}/run_enabled ready (change it with scripts/enable.sh / disable.sh)"
