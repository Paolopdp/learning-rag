#!/usr/bin/env bash
set -euo pipefail

API_BASE="${RAG_API_BASE:-http://127.0.0.1:8000}"
WORKSPACE_ID="${RAG_PROMPTFOO_WORKSPACE_ID:-11111111-1111-1111-1111-111111111111}"
CONFIG_PATH="${RAG_PROMPTFOO_CONFIG:-promptfoo/rag_policy_eval.yaml}"
ARTIFACT_DIR="${RAG_PROMPTFOO_ARTIFACT_DIR:-artifacts/promptfoo}"
PROMPTFOO_VERSION="${PROMPTFOO_VERSION:-0.120.23}"
PROMPTFOO_BIN="${PROMPTFOO_BIN:-npx --yes promptfoo@${PROMPTFOO_VERSION}}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required (>= 20.10, recommended 22.x)."
  exit 1
fi

node_version_raw="$(node -v | sed 's/^v//')"
node_major="$(printf '%s' "$node_version_raw" | cut -d. -f1)"
node_minor="$(printf '%s' "$node_version_raw" | cut -d. -f2)"
if [ "$node_major" -lt 20 ] || { [ "$node_major" -eq 20 ] && [ "$node_minor" -lt 10 ]; }; then
  echo "Detected Node.js $node_version_raw, but promptfoo requires >= 20.10."
  echo "Upgrade Node (recommended: 22.x), then rerun."
  exit 1
fi

mkdir -p "$ARTIFACT_DIR"

ready=0
for _ in $(seq 1 40); do
  if curl -fsS "$API_BASE/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "Backend is not reachable at $API_BASE"
  exit 1
fi

echo "Ingesting demo dataset for promptfoo evaluation..."
curl -fsS -X POST "$API_BASE/workspaces/$WORKSPACE_ID/ingest/demo" >/dev/null

echo "Running promptfoo evaluation..."
# shellcheck disable=SC2086
$PROMPTFOO_BIN eval \
  -c "$CONFIG_PATH" \
  --output "$ARTIFACT_DIR/results.json"

echo "Promptfoo evaluation completed."
echo "Artifact: $ARTIFACT_DIR/results.json"
