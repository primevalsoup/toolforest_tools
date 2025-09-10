#!/usr/bin/env bash
set -euo pipefail
export CDK_DEFAULT_ACCOUNT=${CDK_DEFAULT_ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
export CDK_DEFAULT_REGION=${CDK_DEFAULT_REGION:-us-west-2}
ENV=${ENV:-dev}
OWNER=${OWNER:-gerrit@toolforest.io}

if ! command -v uv &>/dev/null; then
  echo "uv is not installed. Install from https://github.com/astral-sh/uv" >&2
  exit 1
fi

uv venv --python 3.12
. .venv/bin/activate
uv pip install -r requirements.txt

ENV="$ENV" OWNER="$OWNER" npx cdk deploy --require-approval never
