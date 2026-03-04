#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker compose -f "$ROOT_DIR/docker-compose.yml" --profile edge up -d edge-proxy

echo "Edge proxy is running at http://127.0.0.1:8080"
echo "Backend target is http://127.0.0.1:8000 (must already be running)."
