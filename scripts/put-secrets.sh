#!/usr/bin/env bash
# Store the bot's secrets in SSM Parameter Store (SecureString) under /navi/<env>/.
# Values are typed at the prompt (never echoed, never written to a file, never in shell history) and sent to AWS
# through stdin, so they do not appear in the process list. Blank = skip that value. Run it yourself; do not paste
# secrets into chat.
source "$(dirname "$0")/lib.sh"
require_real_config

for name in discord_token gemini_api_key_free gemini_api_key_paid partner_bot_api_key; do
  read -rsp "Value for ${PREFIX}/${name} (blank = skip): " v; echo
  if [ -n "$v" ]; then
    V="$v" jq -n --arg n "${PREFIX}/${name}" '{Name:$n, Type:"SecureString", Overwrite:true, Value:env.V}' \
      | aws ssm put-parameter --cli-input-json file:///dev/stdin >/dev/null
    echo "  saved ${PREFIX}/${name}"
  fi
  unset v
done
# The bot stays idle until you flip this (scripts/enable.sh).
aws ssm put-parameter --name "${PREFIX}/run_enabled" --type String --value false >/dev/null
echo "  ${PREFIX}/run_enabled = false"
