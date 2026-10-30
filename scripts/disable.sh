#!/usr/bin/env bash
# Rollback / maintenance: stop the bot (run_enabled=false). The instance keeps idling and the databases stay replicated.
source "$(dirname "$0")/lib.sh"
aws ssm put-parameter --name "${PREFIX}/run_enabled" --type String --value false --overwrite >/dev/null
cmd="$(run_on_instance 'systemctl restart navi')" && echo "run_enabled=false; the bot will idle after the restart (command $cmd)."
