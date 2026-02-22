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
GARAK_SUMMARY_FILE="${RAG_GARAK_SUMMARY_FILE:-$ARTIFACT_DIR/garak-summary.json}"
GARAK_KEEP_RAW_ARTIFACTS="${RAG_GARAK_KEEP_RAW_ARTIFACTS:-0}"

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
mkdir -p "$(dirname "$GARAK_SUMMARY_FILE")"

if [[ "$GARAK_REPORT_PREFIX" == *"/"* ]]; then
  echo "GARAK_REPORT_PREFIX must be a filename prefix, not a path."
  echo "Use RAG_GARAK_REPORT_DIR for directory output control."
  exit 1
fi

report_dir_abs="$(cd "$GARAK_REPORT_DIR" && pwd)"
summary_file_abs="$(cd "$(dirname "$GARAK_SUMMARY_FILE")" && pwd)/$(basename "$GARAK_SUMMARY_FILE")"

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
run_started_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
run_started_epoch="$(date +%s)"
raw_output_file="$(mktemp)"

set +e
# shellcheck disable=SC2086
$GARAK_BIN \
  --config "$runtime_config_file" \
  --target_type rest \
  --target_name "$query_uri" \
  --generator_option_file "$generator_options_file" \
  --probes "$GARAK_PROBES" \
  --generations "$GARAK_GENERATIONS" \
  --report_prefix "$GARAK_REPORT_PREFIX" \
  >"$raw_output_file" 2>&1
garak_exit_code=$?
set -e

run_finished_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
run_finished_epoch="$(date +%s)"
run_duration_seconds=$((run_finished_epoch - run_started_epoch))

report_jsonl_path="$report_dir_abs/$GARAK_REPORT_PREFIX.report.jsonl"
report_html_path="$report_dir_abs/$GARAK_REPORT_PREFIX.report.html"

"$PYTHON_BIN" - "$report_jsonl_path" "$summary_file_abs" "$GARAK_PROBES" "$GARAK_GENERATIONS" "$garak_exit_code" "$run_started_at" "$run_finished_at" "$run_duration_seconds" <<'PY'
import json
import os
import sys

report_path = sys.argv[1]
summary_path = sys.argv[2]
probes = sys.argv[3]
generations = int(sys.argv[4])
exit_code = int(sys.argv[5])
started_at = sys.argv[6]
finished_at = sys.argv[7]
duration_seconds = int(sys.argv[8])

eval_rows = []
if os.path.exists(report_path):
    with open(report_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("entry_type") != "eval":
                continue
            eval_rows.append(
                {
                    "probe": record.get("probe"),
                    "detector": record.get("detector"),
                    "passed": record.get("passed"),
                    "total": record.get("total"),
                    "nones": record.get("nones"),
                }
            )

llm_enabled = os.getenv("RAG_USE_LLM", "0").lower() in {"1", "true", "yes"}
summary = {
    "scan_mode": "llm_generation" if llm_enabled else "retrieval_only",
    "garak_exit_code": exit_code,
    "probes": probes,
    "generations": generations,
    "started_at": started_at,
    "finished_at": finished_at,
    "duration_seconds": duration_seconds,
    "report_found": os.path.exists(report_path),
    "eval": eval_rows,
}

with open(summary_path, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY

if [ "$GARAK_KEEP_RAW_ARTIFACTS" != "1" ]; then
  rm -f "$report_jsonl_path" "$report_html_path"
fi

rm -f "$raw_output_file"

if [ "$garak_exit_code" -ne 0 ]; then
  echo "Garak scan failed with exit code $garak_exit_code. Raw output is withheld for compliance."
  echo "Sanitized summary: $summary_file_abs"
  exit "$garak_exit_code"
fi

echo "Garak scan completed."
echo "Sanitized summary: $summary_file_abs"
