# Governance and Audit

This project includes a minimal governance baseline focused on traceability and safe defaults.

## What is logged
- Event metadata for key actions (`auth_register`, `auth_login`, `ingest_demo`, `query`).
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
- Document inventory endpoint: `GET /workspaces/{workspace_id}/documents?limit=50&offset=0`
- Classification update endpoint:
  `PATCH /workspaces/{workspace_id}/documents/{document_id}/classification`
- Allowed labels: `public`, `internal`, `confidential`, `restricted`
- Default label at ingestion: `internal`

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
