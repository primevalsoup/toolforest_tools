#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv &>/dev/null; then
  echo "uv is not installed. Install from https://github.com/astral-sh/uv" >&2
  exit 1
fi

uv venv --python 3.12
. .venv/bin/activate
uv pip install -r requirements.txt
pytest -q "$@"
