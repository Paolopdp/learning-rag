#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
cd $BACKEND_DIR
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn app.main:app --reload
cd -
