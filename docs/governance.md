# Governance and Audit

This project includes a minimal governance baseline focused on traceability and safe defaults.

## What is logged
- Event metadata for key actions (`auth_register`, `auth_login`, `ingest_demo`, `ingest_upload`, `query`).
- Actor and scope fields (`user_id`, `workspace_id`) when available.
- Event timestamp (`created_at`) and structured payload (`payload`).
- Action outcome (`payload.outcome`) with values `success` or `failure`.

## What is not logged
- Raw prompts or full document text.
- Sensitive payload keys are redacted server-side before persistence.

## Audit API
- Endpoint: `GET /workspaces/{workspace_id}/audit?limit=20`
- Access: requires workspace membership (or auth-disabled test mode).
- Ordering: newest first (`created_at DESC`).
- Pagination: currently limit-only (bounded server-side).

## Classification labels
- Upload ingestion endpoint: `POST /workspaces/{workspace_id}/ingest` (multipart files)
- Document inventory endpoint: `GET /workspaces/{workspace_id}/documents?limit=50&offset=0`
- Classification update endpoint:
  `PATCH /workspaces/{workspace_id}/documents/{document_id}/classification`
- Allowed labels: `public`, `internal`, `confidential`, `restricted`
- Default label at ingestion: `internal`
- Query policy enforcement:
  - `admin`: can retrieve all labels.
  - `member`: can retrieve only `public` and `internal`.
  - Unknown roles are denied by default except `public`.
- Query API response (`POST /workspaces/{workspace_id}/query`) includes:
  - `policy.policy_enforced`
  - `policy.policy_filtering_mode`
  - `policy.access_role`
  - `policy.allowed_classification_labels`
  - `policy.candidate_results`
  - `policy.returned_results`
- Query audit payload includes policy fields:
  - `access_role`
  - `allowed_classification_labels`
  - `candidate_results`
  - `policy_filtering_mode` (`in_retrieval`)

## Workspace member management
- Members endpoint: `GET /workspaces/{workspace_id}/members`
- Add member endpoint: `POST /workspaces/{workspace_id}/members` (admin only)
- Role update endpoint: `PATCH /workspaces/{workspace_id}/members/{user_id}/role` (admin only)
- Remove member endpoint: `DELETE /workspaces/{workspace_id}/members/{user_id}` (admin only)
- Safety rule: the last workspace admin cannot be demoted or removed.

## Storage and index
- Audit logs are stored only when `RAG_STORE=postgres`.
- Retrieval is optimized for workspace-scoped chronological reads with:
  - `ix_audit_logs_workspace_created_at (workspace_id, created_at DESC)`

## Operational behavior
- Audit logging is best-effort and must not break ingestion/query flows.
- Invalid `workspace_id` values are rejected early with HTTP 400.
- Query throttling emits structured observability logs:
  - `query_rate_limit_near_exhaustion` when remaining budget is low.
  - `query_rate_limit_denied` on enforced `429` responses.
- Login throttling emits structured observability logs:
  - `auth_login_rate_limit_near_exhaustion` when remaining budget is low.
  - `auth_login_rate_limit_denied` on enforced `429` responses.
- Register throttling emits structured observability logs:
  - `auth_register_rate_limit_near_exhaustion` when remaining budget is low.
  - `auth_register_rate_limit_denied` on enforced `429` responses.
- Auth-token failure throttling emits structured observability logs:
  - `auth_token_failure` for `401` token failure reasons.
  - `auth_token_rate_limit_near_exhaustion` when remaining budget is low.
  - `auth_token_rate_limit_denied` on enforced `429` responses.
- Upload-ingest throttling emits structured observability logs:
  - `ingest_rate_limit_near_exhaustion` when remaining budget is low.
  - `ingest_rate_limit_denied` on enforced `429` responses.
- Proxy/header trust model:
  - Forwarded client IP headers are honored only for `RAG_TRUSTED_PROXIES`.
  - If client IP is unavailable, auth login/register checks fall back to subject scope only.
- Optional edge throttle layer:
  - Nginx profile `edge` adds coarse IP-based limits for `/auth/login`, `/auth/register`, `/workspaces/{workspace_id}/query`, and `/workspaces/{workspace_id}/ingest`.
  - Edge denies return HTTP `429` with header `X-RateLimit-Layer: edge`.
  - Edge proxy accepts up to `60m` request bodies so default backend multipart uploads are not rejected before app validation.
  - Edge proxy overwrites `X-Forwarded-For` with the immediate client IP before forwarding to the backend.
  - Edge budgets are intentionally coarse and do not replace app-level workspace/user controls.

## Auth Abuse Control
- Endpoint: `POST /auth/login`
- Default limits:
  - `RAG_AUTH_LOGIN_RATE_LIMIT_REQUESTS=10`
  - `RAG_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS=60`
- Keying strategy:
  - Client IP scope
  - Login subject hash scope (normalized email hash)
- Response behavior:
  - Returns HTTP `429` with `Retry-After` when either scope exceeds budget.

## Auth Register Abuse Control
- Endpoint: `POST /auth/register`
- Default limits:
  - `RAG_AUTH_REGISTER_RATE_LIMIT_REQUESTS=5`
  - `RAG_AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS=60`
- Keying strategy:
  - Client IP scope
  - Registration subject hash scope (normalized email hash)
- Response behavior:
  - Returns HTTP `429` with `Retry-After` when either scope exceeds budget.

## Auth Token-Failure Abuse Control
- Endpoints: all bearer-protected endpoints using auth dependency.
- Default limits:
  - `RAG_AUTH_TOKEN_RATE_LIMIT_REQUESTS=30`
  - `RAG_AUTH_TOKEN_RATE_LIMIT_WINDOW_SECONDS=60`
- Keying strategy:
  - Client IP scope (`ip:{client_ip}`)
- Failure reasons monitored:
  - `missing_bearer_token`
  - `invalid_token`
  - `invalid_token_payload`
  - `token_user_not_found`
- Response behavior:
  - Normal auth failures return HTTP `401`.
  - Repeated failures beyond budget return HTTP `429` with `Retry-After`.

## Upload Ingest Abuse Control
- Endpoint: `POST /workspaces/{workspace_id}/ingest`
- Default limits:
  - `RAG_INGEST_RATE_LIMIT_REQUESTS=8`
  - `RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS=60`
- Scope-specific overrides:
  - `RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE`
  - `RAG_INGEST_RATE_LIMIT_REQUESTS_USER`
- Keying strategy:
  - User scope key (`user:{user_id}`)
  - Workspace scope key (`workspace:{workspace_id}`) after membership verification
- Response behavior:
  - Returns HTTP `429` with `Retry-After` when either scope exceeds budget.

## Edge/Global Throttle Baseline
- Local profile:
  - `docker compose --profile edge up -d edge-proxy`
- Config file:
  - `infra/nginx/rag-edge.conf`
- Smoke check:
  - `scripts/smoke_edge_rate_limit.sh`
- Production guidance:
  - Keep edge thresholds higher than app-level budgets to avoid masking app-level observability.
  - Limit trusted proxy CIDRs narrowly when enabling `RAG_TRUSTED_PROXIES`.

## Query Throttle Presets
- Local/dev example:
  - `RAG_QUERY_RATE_LIMIT_REQUESTS=100`
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER=80`
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN=150`
  - `RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS=60`
- Staging example:
  - `RAG_QUERY_RATE_LIMIT_REQUESTS=30`
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER=20`
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN=40`
  - `RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS=60`
- Production baseline example:
  - `RAG_QUERY_RATE_LIMIT_REQUESTS=20`
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER=10`
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN=30`
  - `RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS=60`
- Tune for your workload:
  - Lower member limits first when abuse pressure increases.
  - Keep admin limits higher to avoid blocking governance operations during incidents.

## Alerting Guidance
- Alert on sustained denies:
  - Trigger when `query_rate_limit_denied` appears repeatedly for the same workspace over a short window.
- Alert on budget pressure:
  - Trigger when `query_rate_limit_near_exhaustion` volume grows quickly, even if denies are still low.
- Alert on degraded backend mode:
  - Trigger immediately on `query_rate_limit_redis_init_failed_fallback_memory`.
  - Trigger on repeated `query_rate_limit_redis_unavailable_fallback_memory` warnings.
  - Clear incident when `query_rate_limit_redis_recovered` appears.
- Concrete LogQL examples and dashboard suggestions:
  - See `docs/operations.md`.

## Dashboard Fields
- Use these structured fields for dashboard filters/aggregations:
  - `workspace_id`
  - `access_role`
  - `rate_limit_backend`
  - `rate_limit_requests`
  - `rate_limit_window_seconds`
  - `rate_limit_remaining`
  - `rate_limit_retry_after_seconds`

## Rate-Limit Runbook
- Step 1: confirm event type and scope (`near_exhaustion` vs `denied`, affected `workspace_id`, affected `access_role`).
- Step 2: verify backend mode (`rate_limit_backend=redis` vs fallback `memory`).
- Step 3: if fallback is active, investigate Redis availability first before changing limits.
- Step 4: if Redis is healthy, tune `RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER` before changing admin/global values.
- Step 5: deploy updated env values and verify decrease in `query_rate_limit_denied` volume.

## Evaluation (Promptfoo)
- Config: `promptfoo/rag_policy_eval.yaml`
- Runner: `scripts/run_promptfoo_eval.sh`
- Current CI mode: blocking core-invariant gate (`promptfoo-eval`) with JSON artifact upload.
- Gate validator: `scripts/check_promptfoo_results.py` (requires all rows pass and return HTTP 200).

## Evaluation Gate Policy
- Gate levels and promotion rules are documented in `docs/eval-gates.md`.
- Current blocking gates include tests, policy smoke, promptfoo core invariants, and security scans.
- Presidio runtime smoke currently runs on Python `3.13` due an upstream spaCy Python `3.14` compatibility issue (`https://github.com/explosion/spaCy/issues/13895`).

## Query Security Testing (Garak Baseline)
- Runner: `scripts/run_garak_scan.sh`
- Current CI mode: non-blocking nightly/manual workflow (`.github/workflows/llm-security.yml`) in retrieval mode (`RAG_USE_LLM=0`)
- Uploaded artifact: sanitized summary only (`garak-summary`)
- Raw prompt/response report artifacts are disabled by default for compliance

## LLM Generation Security Testing (Garak)
- Runner: `scripts/run_garak_scan.sh`
- Current CI mode: non-blocking weekly/manual workflow (`.github/workflows/llm-generation-security.yml`) with `RAG_USE_LLM=1`
- CI model: `TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF` (`tinyllama-1.1b-chat-v1.0.Q2_K.gguf`)
- Uploaded artifact: sanitized summary only (`garak-llm-summary`)
- Raw prompt/response report artifacts are disabled by default for compliance

## Local verification
```bash
# Run backend with postgres + migrations
./scripts/launch_backend.sh

# In another terminal, run end-to-end role policy smoke test
./scripts/smoke_query_policy_roles.sh

# Generate events
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@local","password":"change-me-now"}'

# Read workspace audit events
curl -H "Authorization: Bearer TOKEN" \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/audit?limit=20"

# List documents and update one classification label
curl -H "Authorization: Bearer TOKEN" \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/documents"
curl -X PATCH \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"classification_label":"restricted"}' \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/documents/DOCUMENT_ID/classification"

# List and manage workspace members
curl -H "Authorization: Bearer TOKEN" \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/members"
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"email":"member@local","role":"member"}' \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/members"
```
