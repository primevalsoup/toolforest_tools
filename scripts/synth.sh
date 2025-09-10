#!/usr/bin/env bash
set -euo pipefail
export CDK_DEFAULT_ACCOUNT=${CDK_DEFAULT_ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
export CDK_DEFAULT_REGION=${CDK_DEFAULT_REGION:-us-west-2}
ENV=${ENV:-dev}
uv venv --python 3.12
. .venv/bin/activate
uv pip install -r requirements.txt
npx cdk synth --quiet
