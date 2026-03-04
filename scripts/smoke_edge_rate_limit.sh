#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDGE_BASE_URL="${EDGE_BASE_URL:-http://127.0.0.1:8080}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://127.0.0.1:8000/health}"
ATTEMPTS="${EDGE_SMOKE_ATTEMPTS:-20}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required."
  exit 1
fi

if ! curl -fsS "$BACKEND_HEALTH_URL" >/dev/null; then
  echo "Backend health check failed at $BACKEND_HEALTH_URL"
  echo "Start backend first (for example ./scripts/launch_backend.sh)."
  exit 1
fi

docker compose -f "$ROOT_DIR/docker-compose.yml" --profile edge up -d edge-proxy >/dev/null

echo "Running edge throttle smoke against $EDGE_BASE_URL/auth/login ($ATTEMPTS attempts)..."

edge_denied=0
backend_denied=0
unauthorized=0

for _ in $(seq 1 "$ATTEMPTS"); do
  headers_file="$(mktemp)"
  status_code="$(
    curl -sS -o /dev/null -D "$headers_file" -w "%{http_code}" \
      -X POST "$EDGE_BASE_URL/auth/login" \
      -H "Content-Type: application/json" \
      -d '{"email":"smoke@local","password":"wrong-password"}'
  )"

  case "$status_code" in
    401)
      unauthorized=$((unauthorized + 1))
      ;;
    429)
      if grep -qi '^X-RateLimit-Layer: edge$' "$headers_file"; then
        edge_denied=$((edge_denied + 1))
      else
        backend_denied=$((backend_denied + 1))
      fi
      ;;
  esac

  rm -f "$headers_file"
done

echo "Smoke results:"
echo "  unauthorized_401=$unauthorized"
echo "  edge_denied_429=$edge_denied"
echo "  backend_denied_429=$backend_denied"

if [ "$edge_denied" -lt 1 ]; then
  echo "Expected at least one edge-level 429 (X-RateLimit-Layer: edge), found none."
  exit 1
fi

echo "Edge throttling smoke passed."
