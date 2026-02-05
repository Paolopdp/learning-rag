# Governance and Audit

This project includes a minimal governance baseline focused on traceability and safe defaults.

## What is logged
- Event metadata for key actions (`auth_register`, `auth_login`, `ingest_demo`, `query`).
- Actor and scope fields (`user_id`, `workspace_id`) when available.
- Event timestamp (`created_at`) and structured payload (`payload`).

## What is not logged
- Raw prompts or full document text.
- Sensitive payload keys are redacted server-side before persistence.

## Audit API
- Endpoint: `GET /workspaces/{workspace_id}/audit?limit=20`
- Access: requires workspace membership (or auth-disabled test mode).
- Ordering: newest first (`created_at DESC`).
- Pagination: currently limit-only (bounded server-side).

## Storage and index
- Audit logs are stored only when `RAG_STORE=postgres`.
- Retrieval is optimized for workspace-scoped chronological reads with:
  - `ix_audit_logs_workspace_created_at (workspace_id, created_at DESC)`

## Operational behavior
- Audit logging is best-effort and must not break ingestion/query flows.
- Invalid `workspace_id` values are rejected early with HTTP 400.

## Local verification
```bash
# Run backend with postgres + migrations
./scripts/launch_backend.sh

# Generate events
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@local","password":"change-me-now"}'

# Read workspace audit events
curl -H "Authorization: Bearer TOKEN" \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/audit?limit=20"
```
