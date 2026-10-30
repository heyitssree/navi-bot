#!/usr/bin/env bash
# Let the bot run (run_enabled=true) and restart it. Use at cutover, after the secrets are stored.
source "$(dirname "$0")/lib.sh"
aws ssm put-parameter --name "${PREFIX}/run_enabled" --type String --value true --overwrite >/dev/null
cmd="$(run_on_instance 'systemctl restart navi')" && echo "run_enabled=true; restart requested (command $cmd)."
