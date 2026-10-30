#!/usr/bin/env bash
# Store non-secret settings the bot reads at startup (plain String parameters). Blank = skip.
source "$(dirname "$0")/lib.sh"
require_real_config

for name in owner_id guild_id general_channel mod_channel_name; do
  read -rp "Value for ${PREFIX}/${name} (blank = skip): " v
  [ -n "$v" ] && aws ssm put-parameter --name "${PREFIX}/${name}" --type String --value "$v" --overwrite >/dev/null && echo "  saved ${PREFIX}/${name}"
done
