#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed."
  exit 1
fi

cd "$BACKEND_DIR"

if [ ! -d .venv ]; then
  uv venv --python 3.13
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [ "${SMOKE_DB_RESET:-0}" = "1" ]; then
  docker compose down
fi

docker compose up -d db

uv pip install -e ".[dev]"

alembic upgrade head

export RAG_STORE=postgres
export RAG_DATABASE_URL="${RAG_DATABASE_URL:-postgresql+psycopg://rag:rag@localhost:5432/rag}"

HOST="${RAG_HOST:-127.0.0.1}"
PORT="${RAG_PORT:-8000}"

uvicorn app.main:app --host "$HOST" --port "$PORT" &
API_PID=$!

cleanup() {
  kill "$API_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ready=0
for _ in $(seq 1 20); do
  if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [ "$ready" -ne 1 ]; then
  echo "API did not become ready."
  exit 1
fi

auth_payload='{"email":"demo@local","password":"change-me-now"}'

auth_response="$(curl -fsS -X POST "http://$HOST:$PORT/auth/register" \
  -H "Content-Type: application/json" \
  -d "$auth_payload" || true)"

if [ -z "$auth_response" ]; then
  auth_response="$(curl -fsS -X POST "http://$HOST:$PORT/auth/login" \
    -H "Content-Type: application/json" \
    -d "$auth_payload")"
fi

if [ -z "$auth_response" ]; then
  echo "Auth failed."
  exit 1
fi

token="$(printf '%s' "$auth_response" | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
workspace_id="$(printf '%s' "$auth_response" | python -c 'import json,sys; data=json.load(sys.stdin); ws=data.get("default_workspace") or {}; print(ws.get("id",""))')"

if [ -z "$workspace_id" ]; then
  workspace_id="$(curl -fsS "http://$HOST:$PORT/workspaces" \
    -H "Authorization: Bearer $token" | \
    python -c 'import json,sys; data=json.load(sys.stdin); print(data[0]["id"] if data else "")')"
fi

if [ -z "$workspace_id" ]; then
  echo "Workspace not found."
  exit 1
fi

curl -fsS -X POST "http://$HOST:$PORT/workspaces/$workspace_id/ingest/demo" \
  -H "Authorization: Bearer $token" >/dev/null

response="$(curl -fsS -X POST "http://$HOST:$PORT/workspaces/$workspace_id/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $token" \
  -d "{\"question\": \"Che cos’è SPID e a cosa serve?\", \"top_k\": 3}")"

if [ -z "$response" ]; then
  echo "Empty response from /query"
  exit 1
fi

printf '%s' "$response" | python -c 'import json,sys; payload=json.load(sys.stdin); \
assert payload.get("answer"), "Missing answer"; \
assert payload.get("citations"), "Missing citations"; \
print("OK: answer + citations returned")'

audit_response="$(curl -fsS "http://$HOST:$PORT/workspaces/$workspace_id/audit?limit=5" \
  -H "Authorization: Bearer $token")"

if [ -z "$audit_response" ]; then
  echo "Empty response from /audit"
  exit 1
fi

printf '%s' "$audit_response" | python -c 'import json,sys; payload=json.load(sys.stdin); \
assert isinstance(payload, list), "Audit payload must be a list"; \
assert len(payload) > 0, "Audit log is empty"; \
print("OK: audit events returned")'
