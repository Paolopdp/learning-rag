#!/usr/bin/env bash
set -euo pipefail

API_BASE="${RAG_API_BASE:-http://127.0.0.1:8000}"
ADMIN_EMAIL="${RAG_POLICY_ADMIN_EMAIL:-policy-admin@local}"
MEMBER_EMAIL="${RAG_POLICY_MEMBER_EMAIL:-policy-member@local}"
PASSWORD="${RAG_POLICY_PASSWORD:-change-me-now}"
PYTHON_BIN="${PYTHON_BIN:-}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required."
  exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "python3 (or python) is required."
    exit 1
  fi
fi

request() {
  local response
  response="$(curl -sS -w $'\n%{http_code}' "$@")"
  HTTP_BODY="${response%$'\n'*}"
  HTTP_CODE="${response##*$'\n'}"
}

auth_or_register() {
  local email="$1"
  local payload

  payload="$(printf '{"email":"%s","password":"%s"}' "$email" "$PASSWORD")"

  request \
    -X POST "$API_BASE/auth/register" \
    -H "Content-Type: application/json" \
    -d "$payload"
  if [ "$HTTP_CODE" = "200" ]; then
    printf '%s' "$HTTP_BODY"
    return 0
  fi

  request \
    -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "$payload"
  if [ "$HTTP_CODE" != "200" ]; then
    echo "Auth failed for $email (status: $HTTP_CODE)"
    printf '%s\n' "$HTTP_BODY"
    exit 1
  fi
  printf '%s' "$HTTP_BODY"
}

require_healthy_api() {
  request "$API_BASE/health"
  if [ "$HTTP_CODE" != "200" ]; then
    echo "API is not healthy at $API_BASE"
    exit 1
  fi
}

echo "Checking API health..."
require_healthy_api

echo "Authenticating admin and member users..."
admin_auth="$(auth_or_register "$ADMIN_EMAIL")"
member_auth="$(auth_or_register "$MEMBER_EMAIL")"

admin_token="$(printf '%s' "$admin_auth" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
member_token="$(printf '%s' "$member_auth" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

workspace_name="Policy Smoke $(date +%s)"
request \
  -X POST "$API_BASE/workspaces" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $admin_token" \
  -d "$(printf '{"name":"%s"}' "$workspace_name")"
if [ "$HTTP_CODE" != "200" ]; then
  echo "Failed to create workspace (status: $HTTP_CODE)"
  printf '%s\n' "$HTTP_BODY"
  exit 1
fi
workspace_id="$(printf '%s' "$HTTP_BODY" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

echo "Workspace created: $workspace_id"

echo "Adding member to workspace..."
request \
  -X POST "$API_BASE/workspaces/$workspace_id/members" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $admin_token" \
  -d "$(printf '{"email":"%s","role":"member"}' "$MEMBER_EMAIL")"

if [ "$HTTP_CODE" != "200" ]; then
  echo "Add member endpoint returned status $HTTP_CODE, validating membership via list..."
fi

request \
  "$API_BASE/workspaces/$workspace_id/members" \
  -H "Authorization: Bearer $admin_token"
if [ "$HTTP_CODE" != "200" ]; then
  echo "Failed to list members (status: $HTTP_CODE)"
  printf '%s\n' "$HTTP_BODY"
  exit 1
fi
printf '%s' "$HTTP_BODY" | "$PYTHON_BIN" -c 'import json,sys; members=json.load(sys.stdin); target_email=sys.argv[1]; assert any(m.get("email")==target_email for m in members), f"Member {target_email} is not present in workspace."' "$MEMBER_EMAIL"

echo "Ingesting demo data..."
request \
  -X POST "$API_BASE/workspaces/$workspace_id/ingest/demo" \
  -H "Authorization: Bearer $admin_token"
if [ "$HTTP_CODE" != "200" ]; then
  echo "Ingest failed (status: $HTTP_CODE)"
  printf '%s\n' "$HTTP_BODY"
  exit 1
fi

echo "Setting all documents to restricted..."
request \
  "$API_BASE/workspaces/$workspace_id/documents?limit=200&offset=0" \
  -H "Authorization: Bearer $admin_token"
if [ "$HTTP_CODE" != "200" ]; then
  echo "Document inventory fetch failed (status: $HTTP_CODE)"
  printf '%s\n' "$HTTP_BODY"
  exit 1
fi

mapfile -t document_ids < <(
  printf '%s' "$HTTP_BODY" | "$PYTHON_BIN" -c 'import json,sys; [print(item["id"]) for item in json.load(sys.stdin)]'
)
if [ "${#document_ids[@]}" -eq 0 ]; then
  echo "No documents found after ingest."
  exit 1
fi

for document_id in "${document_ids[@]}"; do
  request \
    -X PATCH "$API_BASE/workspaces/$workspace_id/documents/$document_id/classification" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $admin_token" \
    -d '{"classification_label":"restricted"}'
  if [ "$HTTP_CODE" != "200" ]; then
    echo "Failed to update classification for $document_id (status: $HTTP_CODE)"
    printf '%s\n' "$HTTP_BODY"
    exit 1
  fi
done

query_payload='{"question":"Che cos’è SPID e a cosa serve?","top_k":3}'

echo "Running admin query..."
request \
  -X POST "$API_BASE/workspaces/$workspace_id/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $admin_token" \
  -d "$query_payload"
if [ "$HTTP_CODE" != "200" ]; then
  echo "Admin query failed (status: $HTTP_CODE)"
  printf '%s\n' "$HTTP_BODY"
  exit 1
fi
printf '%s' "$HTTP_BODY" | "$PYTHON_BIN" -c 'import json,sys; payload=json.load(sys.stdin); assert payload.get("citations"), "Admin query should return citations."; assert payload.get("policy", {}).get("access_role") == "admin", "Expected admin role in policy payload."; print("OK: admin query returns results.")'

echo "Running member query..."
request \
  -X POST "$API_BASE/workspaces/$workspace_id/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $member_token" \
  -d "$query_payload"
if [ "$HTTP_CODE" != "200" ]; then
  echo "Member query failed (status: $HTTP_CODE)"
  printf '%s\n' "$HTTP_BODY"
  exit 1
fi
printf '%s' "$HTTP_BODY" | "$PYTHON_BIN" -c 'import json,sys; payload=json.load(sys.stdin); assert payload.get("answer") == "Nessun risultato.", "Member should not retrieve restricted data."; assert payload.get("citations") == [], "Member citations should be empty with all documents restricted."; policy=payload.get("policy", {}); assert policy.get("access_role") == "member", "Expected member role in policy payload."; assert policy.get("returned_results") == 0, "Expected zero returned results for member."; print("OK: member query is correctly filtered by policy.")'

echo "Policy smoke test passed."
echo "Workspace used for the run: $workspace_id"
