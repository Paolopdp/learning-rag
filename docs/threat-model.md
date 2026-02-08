# Threat Model (MVP)

Last updated: 2026-02-08

This document describes the current threat model for the local-first RAG assistant.
It is an engineering artifact for design and review, not a legal/compliance claim.

## Scope
- FastAPI backend endpoints in `backend/app/main.py`
- Auth and workspace authorization in `backend/app/auth.py`
- Retrieval and storage in `backend/app/store.py`
- Audit logging in `backend/app/audit.py`
- Frontend link rendering safeguards in `frontend/src/app/page.tsx`
- CI security workflow in `.github/workflows/ci.yml`

## Trust Boundaries
- Boundary A: browser/client input to backend API.
  Everything from the client is untrusted and must be validated.
- Boundary B: backend API to PostgreSQL.
  Backend controls access and policy decisions before DB reads/writes.
- Boundary C: backend to LLM runtime (optional path).
  Retrieved text is model context, not trusted instructions.
- Boundary D: repository and CI pipeline.
  Secrets/dependencies/artifacts must be scanned and traceable.

## Critical Assets
- Workspace-scoped documents and chunks.
- Classification labels (`public`, `internal`, `confidential`, `restricted`).
- Workspace membership roster and roles.
- Audit trail records and outcomes.
- Access tokens and auth credentials.

## Threat Matrix

| ID | Threat | Current controls | Evidence (tests/scripts) | Status | Residual risk / next action |
|---|---|---|---|---|---|
| TM-01 | Cross-workspace data access via `workspace_id` tampering | Workspace-scoped endpoints require membership via `require_workspace_role`; store queries filter by `workspace_id` | `backend/tests/test_document_inventory.py::test_document_classification_is_workspace_scoped` | Mitigated (MVP) | Keep validating every new workspace endpoint for membership checks. |
| TM-02 | Unauthorized governance mutation (member updates, classification changes) | Admin-only role checks on member mutation endpoints and classification update endpoint | `backend/tests/test_document_inventory.py::test_document_classification_requires_admin_role`, `backend/tests/test_workspace_members.py` | Mitigated (MVP) | Add explicit API contract tests for all admin-only routes in one suite. |
| TM-03 | Sensitive workspace member roster read without audit trace | `workspace_member_read` event with outcome success/failure | `backend/tests/test_workspace_members.py::test_add_workspace_member_and_list`, `backend/tests/test_workspace_members.py::test_list_workspace_members_fails_on_missing_user_record` | Mitigated (MVP) | Add integration-level assertion that audit endpoint returns this event after read. |
| TM-04 | Sensitive document inventory read without audit trace | `document_inventory_read` audit event with limit/offset/returned/outcome | `backend/tests/test_document_inventory.py::test_document_inventory_logs_read_event` | Mitigated (MVP) | Add UI smoke assertion that inventory refresh creates audit entry. |
| TM-05 | Email/account enumeration through member add flow | Generic user-facing error for unknown/already-member; detailed reason only in audit payload | `backend/tests/test_workspace_members.py::test_add_workspace_member_unknown_email_uses_generic_error` | Mitigated (MVP) | Keep generic errors across any future user lookup endpoints. |
| TM-06 | Unsafe link schemes from ingested metadata (phishing/script URLs) | Ingestion sanitizes source URL to `http/https`; frontend renders only safe parsed `http/https` URLs | `backend/tests/test_ingestion.py::test_parse_wikipedia_file_rejects_unsafe_source_url` | Partially mitigated | Add domain allow/block policy and visual warning for external links. |
| TM-07 | Sensitive prompt/content leakage into audit logs | Audit payload key redaction (`question`, `content`, `text`, `source_url`, etc.); default outcome added | `backend/tests/test_audit.py::test_sanitize_payload_redacts_sensitive_keys`, `backend/tests/test_audit.py::test_log_event_adds_default_success_outcome` | Mitigated (MVP) | Expand redaction policy to nested payload structures. |
| TM-08 | Invalid identifier input causing crashes / 500s | UUID guard functions return 400; classification map ignores invalid UUIDs with structured warning | `backend/tests/test_document_inventory.py::test_document_classification_rejects_invalid_document_id`, `backend/tests/test_store.py::test_postgres_classification_map_ignores_invalid_document_ids` | Mitigated (MVP) | Add one centralized error envelope for all validation failures. |
| TM-09 | Retrieval policy bypass due to post-filter truncation | Policy applied in retrieval selection (`allowed_labels` passed to store search) | `backend/tests/test_query_policy.py::test_query_member_still_gets_allowed_results_with_many_forbidden_chunks`, `backend/tests/test_query_policy.py::test_query_filters_restricted_chunks_for_member` | Mitigated (MVP) | Add larger corpus perf+correctness benchmarks. |
| TM-10 | Governance lockout by removing/demoting last admin | Last-admin protection in role update/remove endpoints | `backend/tests/test_workspace_members.py::test_update_workspace_member_role_blocks_last_admin`, `backend/tests/test_workspace_members.py::test_remove_workspace_member_blocks_last_admin` | Mitigated (MVP) | Add incident runbook for admin recovery in docs. |
| TM-11 | Secret leakage or vulnerable dependency in repo/CI | CI includes Gitleaks, Trivy, OSV-Scanner, Syft; CodeQL workflow present | `.github/workflows/ci.yml`, `.github/workflows/codeql.yml` | Mitigated (baseline) | Add policy for fail thresholds and artifact retention. |
| TM-12 | Audit gaps due to best-effort logging failure path | Logging failure does not block business flow (availability-first) and warnings are emitted | `backend/app/audit.py` behavior | Accepted risk | Add retry/dead-letter strategy if stronger audit durability is required. |

## Known Gaps (Planned)
- Prompt injection hardening and output handling guardrails are not yet implemented.
- PII detection/anonymization pipeline is not yet implemented.
- Automated evaluation/security stacks (`promptfoo`, `garak`) are not yet integrated.
- Rate limiting and abuse controls are not yet implemented.
- Ingestion is demo-dataset based (`/ingest/demo`), not full upload/PDF pipeline yet.

## Next Security/Eval Steps
- Step 2: add `promptfoo` evaluation config and CI checks for grounded answers/citations/policy metadata.
- Step 3: add `garak` security scanning job (non-blocking/nightly first).
