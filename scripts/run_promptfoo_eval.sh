#!/usr/bin/env bash
set -euo pipefail

API_BASE="${RAG_API_BASE:-http://127.0.0.1:8000}"
WORKSPACE_ID="${RAG_PROMPTFOO_WORKSPACE_ID:-11111111-1111-1111-1111-111111111111}"
CONFIG_PATH="${RAG_PROMPTFOO_CONFIG:-promptfoo/rag_policy_eval.yaml}"
ARTIFACT_DIR="${RAG_PROMPTFOO_ARTIFACT_DIR:-artifacts/promptfoo}"
RESULTS_PATH="${RAG_PROMPTFOO_RESULTS_PATH:-$ARTIFACT_DIR/results.json}"
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

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
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
raw_output_file="$(mktemp)"
set +e
# shellcheck disable=SC2086
$PROMPTFOO_BIN eval \
  -c "$CONFIG_PATH" \
  --output "$RESULTS_PATH" \
  >"$raw_output_file" 2>&1
promptfoo_exit_code=$?
set -e

if [ "$promptfoo_exit_code" -ne 0 ]; then
  echo "Promptfoo evaluation failed with exit code $promptfoo_exit_code. Raw output is withheld for compliance."
  rm -f "$raw_output_file"
  exit "$promptfoo_exit_code"
fi
rm -f "$raw_output_file"

if [ ! -s "$RESULTS_PATH" ]; then
  echo "Promptfoo results file is missing or empty: $RESULTS_PATH"
  exit 1
fi

python3 - "$RESULTS_PATH" <<'PY'
import json
import sys

results_path = sys.argv[1]
with open(results_path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

result_rows = payload.get("results", {}).get("results", [])
total = len(result_rows)
passed = 0
for row in result_rows:
    if row.get("success") is True and row.get("gradingResult", {}).get("pass") is True:
        passed += 1

print(f"promptfoo_summary total={total} passed={passed} failed={total - passed}")
if total == 0:
    raise SystemExit("Promptfoo produced zero test rows.")
PY

echo "Promptfoo evaluation completed."
echo "Artifact: $RESULTS_PATH"
