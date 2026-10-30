# Thin wrappers (run inside infra/). Uses the local virtualenv; set AWS_PROFILE (default "navi") for diff/deploy.
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
APP := --app ".venv/bin/python app.py"

.PHONY: setup lint test synth lint-cfn diff deploy bootstrap ci clean

setup:      ## Create the virtualenv and install dependencies
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

lint:       ## Ruff
	.venv/bin/ruff check .

test:       ## Infrastructure tests (no AWS access needed)
	.venv/bin/python -m pytest

synth:      ## Synthesize CloudFormation into cdk.out and lint it with cfn-lint
	cdk synth $(APP) --quiet && .venv/bin/cfn-lint cdk.out/*.template.json

diff:       ## Show what a deploy would change (needs AWS credentials, profile navi)
	AWS_PROFILE=$${AWS_PROFILE:-navi} cdk diff $(APP)

bootstrap:  ## One-time CDK bootstrap of the account/region (admin credentials)
	@set -a; . ../scripts/lib.sh; AWS_PROFILE=$${AWS_PROFILE:-navi} cdk bootstrap $(APP) aws://$$NAVI_ACCOUNT/$$NAVI_REGION

deploy:     ## Deploy via ../scripts/deploy.sh (image build + stacks + restart)
	../scripts/deploy.sh

ci: lint test synth

clean:
	rm -rf cdk.out .pytest_cache .ruff_cache
