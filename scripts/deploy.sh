#!/usr/bin/env bash
# Build + push the image and update the stacks (cdk deploy), then restart the bot in place through SSM
# (about 30 seconds of downtime). Infrastructure changes replace the instance; image-only changes just restart it.
source "$(dirname "$0")/lib.sh"
require_real_config
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
(cd "$ROOT/infra" && cdk deploy --all --require-approval broadening --app ".venv/bin/python app.py")
cmd="$(run_on_instance '/opt/navi/update.sh deploy')" && echo "Restart requested via SSM (command $cmd)."
