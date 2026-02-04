#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed."
  exit 1
fi

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  uv venv --python 3.13 "$BACKEND_DIR/.venv"
fi

# shellcheck disable=SC1091
source "$BACKEND_DIR/.venv/bin/activate"

docker compose -f "$ROOT_DIR/docker-compose.yml" up -d db

uv pip install -e "$BACKEND_DIR/.[dev]"

export RAG_STORE=postgres
export RAG_DATABASE_URL="${RAG_DATABASE_URL:-postgresql+psycopg://rag:rag@localhost:5432/rag}"

pushd "$BACKEND_DIR" >/dev/null
alembic upgrade head
uvicorn app.main:app --reload
popd >/dev/null
