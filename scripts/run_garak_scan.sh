#!/usr/bin/env bash
set -euo pipefail

API_BASE="${RAG_API_BASE:-http://127.0.0.1:8000}"
WORKSPACE_ID="${RAG_GARAK_WORKSPACE_ID:-11111111-1111-1111-1111-111111111111}"
ARTIFACT_DIR="${RAG_GARAK_ARTIFACT_DIR:-artifacts/garak}"
PYTHON_BIN="${PYTHON_BIN:-}"
GARAK_BIN="${GARAK_BIN:-}"
GARAK_PROBES="${GARAK_PROBES:-promptinject}"
GARAK_GENERATIONS="${GARAK_GENERATIONS:-1}"
GARAK_REPORT_PREFIX="${GARAK_REPORT_PREFIX:-garak-report}"
GARAK_REPORT_DIR="${RAG_GARAK_REPORT_DIR:-$ARTIFACT_DIR}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required."
  exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "python (or python3) is required."
    exit 1
  fi
fi

if [ -z "$GARAK_BIN" ]; then
  GARAK_BIN="$PYTHON_BIN -m garak"
fi

mkdir -p "$ARTIFACT_DIR"
mkdir -p "$GARAK_REPORT_DIR"

if [[ "$GARAK_REPORT_PREFIX" == *"/"* ]]; then
  echo "GARAK_REPORT_PREFIX must be a filename prefix, not a path."
  echo "Use RAG_GARAK_REPORT_DIR for directory output control."
  exit 1
fi

report_dir_abs="$(cd "$GARAK_REPORT_DIR" && pwd)"

xdg_root="$ARTIFACT_DIR/xdg"
mkdir -p "$xdg_root/data" "$xdg_root/cache" "$xdg_root/config"
export XDG_DATA_HOME="$xdg_root/data"
export XDG_CACHE_HOME="$xdg_root/cache"
export XDG_CONFIG_HOME="$xdg_root/config"

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

echo "Ingesting demo dataset for garak scan..."
curl -fsS -X POST "$API_BASE/workspaces/$WORKSPACE_ID/ingest/demo" >/dev/null

query_uri="$API_BASE/workspaces/$WORKSPACE_ID/query"
generator_options_file="$ARTIFACT_DIR/rest_generator_options.json"
runtime_config_file="$ARTIFACT_DIR/garak_run_config.yaml"

cat >"$generator_options_file" <<EOF
{
  "rest": {
    "RestGenerator": {
      "name": "rag-query",
      "uri": "$query_uri",
      "method": "post",
      "headers": {
        "Content-Type": "application/json"
      },
      "req_template_json_object": {
        "question": "\$INPUT",
        "top_k": 3
      },
      "response_json": true,
      "response_json_field": "answer"
    }
  }
}
EOF

cat >"$runtime_config_file" <<EOF
reporting:
  report_dir: "$report_dir_abs"
EOF

echo "Running garak scan..."
# shellcheck disable=SC2086
$GARAK_BIN \
  --config "$runtime_config_file" \
  --target_type rest \
  --target_name "$query_uri" \
  --generator_option_file "$generator_options_file" \
  --probes "$GARAK_PROBES" \
  --generations "$GARAK_GENERATIONS" \
  --report_prefix "$GARAK_REPORT_PREFIX" \
  2>&1 | tee "$ARTIFACT_DIR/garak-console.log"

echo "Garak scan completed."
echo "Artifacts directory: $ARTIFACT_DIR"
