# RAG Assistant (Governance & Security by Design)

[![CI](https://github.com/Paolopdp/learning-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/Paolopdp/learning-rag/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Paolopdp/learning-rag/actions/workflows/codeql.yml/badge.svg)](https://github.com/Paolopdp/learning-rag/actions/workflows/codeql.yml)

Local-first, open-source RAG system focused on **secure-by-default** AI application engineering. This repo is intentionally learning-first, built in small vertical slices with KISS/Clean Code/TDD where applicable.

## Status
- Backend MVP skeleton is live (auth + workspaces + citations).
- First vertical slice: ingest -> chunk -> embed -> retrieve -> answer with citations.
- Upload ingestion is available for `.txt`, `.md`, `.markdown`, and `.pdf` files.
- Minimal frontend UI is available (auth, upload/demo ingest, query, citations, audit log, document inventory, workspace members).

## Repo Layout
- `backend/` FastAPI service (current focus)
- `frontend/` UI (future)
- `data/` demo dataset + attribution
- `docs/` project docs (LLM setup, etc.)
- `scripts/` helpers

## Requirements
- Python 3.13
- `uv` package manager
- Optional for local LLM: C/C++ toolchain + CMake (for `llama-cpp-python`)
- For Postgres storage: Docker (or a local Postgres 16 + pgvector)

## Quickstart (Backend)
Preferred (scripted, uses Postgres so audit logging works):
```bash
./scripts/launch_backend.sh
```

Manual (equivalent):
```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Postgres + pgvector (Optional but Recommended)
Start the database (if not using the script):
```bash
docker compose up -d db
```

Run migrations (if not using the script):
```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
alembic upgrade head
```

Enable Postgres storage (required for audit logging):
```bash
export RAG_STORE=postgres
export RAG_DATABASE_URL=postgresql+psycopg://rag:rag@localhost:5432/rag
uvicorn app.main:app --reload
```

Smoke test script:
```bash
./scripts/smoke_postgres.sh
```

To reset the DB before the smoke test:
```bash
SMOKE_DB_RESET=1 ./scripts/smoke_postgres.sh
```

Role-policy smoke test (run while backend is up):
```bash
./scripts/smoke_query_policy_roles.sh
```

## Demo: Ingest + Query
```bash
# Register a user (creates a default workspace)
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@local","password":"change-me-now"}'

# Login (get token if already registered)
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@local","password":"change-me-now"}'

# Upload one or more files (replace WORKSPACE_ID + TOKEN)
curl -X POST http://127.0.0.1:8000/workspaces/WORKSPACE_ID/ingest \
  -H "Authorization: Bearer TOKEN" \
  -F "files=@/absolute/path/document1.txt" \
  -F "files=@/absolute/path/document2.pdf"

# Optional: replace existing workspace documents during upload ingest
curl -X POST "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/ingest?replace_existing=true" \
  -H "Authorization: Bearer TOKEN" \
  -F "files=@/absolute/path/document1.md"

# Ingest the bundled demo dataset
curl -X POST http://127.0.0.1:8000/workspaces/WORKSPACE_ID/ingest/demo \
  -H "Authorization: Bearer TOKEN"

# Ask a question (extractive answer + citations)
curl -X POST http://127.0.0.1:8000/workspaces/WORKSPACE_ID/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"question": "Che cos’è SPID e a cosa serve?", "top_k": 3}'

# Audit log (requires Postgres storage)
curl -H "Authorization: Bearer TOKEN" \
  http://127.0.0.1:8000/workspaces/WORKSPACE_ID/audit?limit=20

# Document inventory
curl -H "Authorization: Bearer TOKEN" \
  "http://127.0.0.1:8000/workspaces/WORKSPACE_ID/documents?limit=50&offset=0"

# Update document classification label
curl -X PATCH http://127.0.0.1:8000/workspaces/WORKSPACE_ID/documents/DOCUMENT_ID/classification \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"classification_label":"confidential"}'

# List workspace members
curl -H "Authorization: Bearer TOKEN" \
  http://127.0.0.1:8000/workspaces/WORKSPACE_ID/members

# Add workspace member (user must already exist)
curl -X POST http://127.0.0.1:8000/workspaces/WORKSPACE_ID/members \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"email":"member@local","role":"member"}'

# Update member role
curl -X PATCH http://127.0.0.1:8000/workspaces/WORKSPACE_ID/members/USER_ID/role \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"role":"admin"}'

# Remove member
curl -X DELETE \
  -H "Authorization: Bearer TOKEN" \
  http://127.0.0.1:8000/workspaces/WORKSPACE_ID/members/USER_ID

# List workspaces
curl -H "Authorization: Bearer TOKEN" http://127.0.0.1:8000/workspaces
```
Audit entries store **metadata only** (no raw prompts or document text).
Sensitive keys (e.g., `question`, `content`) are redacted server-side.
Each audit payload includes an `outcome` (`success` or `failure`).
Auth events (register/login) are recorded with metadata only.
Audit logging is best-effort and will not block core API operations if the DB is unavailable.
Invalid workspace IDs return `400` before any processing.
PII redaction is applied both at ingestion-time (stored document text) and response-time (query answer/excerpts) for baseline identifiers (`email`, `IBAN`, Italian tax code, credit card).
Query endpoint now enforces per-workspace rate limiting and returns `429` with `Retry-After` when limits are exceeded.
Rate-limit counters are stored in Redis (Valkey compatible) by default, with automatic in-memory fallback if Redis is unavailable.
Login endpoint enforces abuse-control throttling and returns `429` with `Retry-After` when login attempts exceed configured limits.
Upload ingest endpoint enforces abuse-control throttling and returns `429` with `Retry-After` when request budgets are exceeded.
Governance reference: `docs/governance.md`.
Operations reference: `docs/operations.md`.
Threat model reference: `docs/threat-model.md`.

## Frontend (Minimal UI)
```bash
cd frontend
npm install
npm run dev
```

Set API base if needed:
```bash
export NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
```

## Local LLM (Optional)
The LLM path is **disabled by default** and only used when `RAG_USE_LLM=1`.

```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev,llm]"

export RAG_USE_LLM=1
export RAG_LLM_MODEL_PATH=/absolute/path/to/model.gguf
uvicorn app.main:app --reload
```

More details: `docs/llm.md`.

## Observability (Optional)
Enable OpenTelemetry tracing (console exporter by default):
```bash
export RAG_OTEL_ENABLED=1
uv pip install -e ".[dev,observability]"
uvicorn app.main:app --reload
```

To export to an OTLP collector:
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
export OTEL_SERVICE_NAME=rag-backend
```

Start a local collector (Jaeger):
```bash
docker compose --profile observability up -d jaeger
```

Then open the UI at `http://localhost:16686`.

Rate-limit observability queries and alert examples:
- `docs/operations.md`

## Auth Configuration
Environment variables:
- `RAG_JWT_SECRET` (required in production; default is dev-only)
- `RAG_AUTH_DISABLED=1` to bypass auth (tests/dev only)
- `RAG_CORS_ORIGINS` to override allowed origins (comma-separated)
- `RAG_PII_REDACTION_ENABLED=0` to disable response redaction in local/debug flows
- `RAG_PII_INGEST_REDACTION_ENABLED=0` to disable ingestion-time redaction in local/debug flows
- `RAG_PII_BACKEND=presidio` to use Presidio recognizers when optional dependencies are installed (`regex` is default/fallback)
- `RAG_PII_DEBUG=1` to include Presidio fallback stack traces in logs during troubleshooting
- `RAG_QUERY_RATE_LIMIT_ENABLED=0` to disable query throttling in local/debug flows
- `RAG_QUERY_RATE_LIMIT_REQUESTS` to configure max queries per workspace in window (default `20`)
- `RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER` optional member-specific max queries per workspace in window (defaults to `RAG_QUERY_RATE_LIMIT_REQUESTS`)
- `RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN` optional admin-specific max queries per workspace in window (defaults to `RAG_QUERY_RATE_LIMIT_REQUESTS`)
- `RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS` to configure throttle window size (default `60`)
- `RAG_AUTH_LOGIN_RATE_LIMIT_ENABLED=0` to disable login throttling in local/debug flows
- `RAG_AUTH_LOGIN_RATE_LIMIT_REQUESTS` to configure max login attempts per key in window (default `10`)
- `RAG_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS` to configure login throttle window size (default `60`)
- `RAG_INGEST_RATE_LIMIT_ENABLED=0` to disable upload-ingest throttling in local/debug flows
- `RAG_INGEST_RATE_LIMIT_REQUESTS` to configure default max ingest requests per key in window (default `8`)
- `RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE` optional workspace-scope max ingest requests in window (defaults to `RAG_INGEST_RATE_LIMIT_REQUESTS`)
- `RAG_INGEST_RATE_LIMIT_REQUESTS_USER` optional user-scope max ingest requests in window (defaults to `RAG_INGEST_RATE_LIMIT_REQUESTS`)
- `RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS` to configure ingest throttle window size (default `60`)
- `RAG_REDIS_URL` to configure Redis/Valkey endpoint for throttling counters (default `redis://localhost:6379/0`)
- `RAG_INGEST_MAX_FILES` max files accepted per upload ingest request (default `10`)
- `RAG_INGEST_MAX_FILE_BYTES` max bytes per uploaded file (default `5242880`)
- `RAG_INGEST_MAX_PDF_PAGES` max parsed pages per uploaded PDF (default `40`)
- `RAG_INGEST_MAX_PDF_TEXT_CHARS` max extracted text characters per uploaded PDF (default `300000`)
- `RAG_DOCUMENT_TITLE_MAX_LENGTH` max document title length accepted by ingestion/store (default `255`)

Password hashing:
- User passwords are hashed with Argon2id (`argon2-cffi`).
- If you are upgrading from older local data generated with the previous SHA-256+bcrypt pre-hash flow, recreate local users (or reset local DB) once.

Optional Presidio backend install:
```bash
cd backend
source .venv/bin/activate
uv pip install -e ".[dev,pii]"
```
Compatibility note:
- Use Python `3.13` for the optional Presidio runtime path for now.
- Python `3.14` currently has an upstream spaCy compatibility issue tracked at `https://github.com/explosion/spaCy/issues/13895`.

If Presidio dependencies/runtime are missing, the backend logs a structured warning once and falls back to regex redaction.

## CI Security Checks
The CI pipeline runs:
- `gitleaks` (secret scanning)
- `osv-scanner` (dependency vulnerabilities)
- `trivy` (filesystem scan)
- `syft` (SBOM generation)
- `promptfoo` eval (blocking on core invariants: pass rows + HTTP 200)
- `pii-presidio-smoke` (non-blocking runtime smoke for optional Presidio backend)

Evaluation gate policy reference: `docs/eval-gates.md`.

Security scan workflows:
- Query baseline: `garak` scan against `/query` in retrieval mode (`RAG_USE_LLM=0`, non-blocking, artifact `garak-summary`) via `.github/workflows/llm-security.yml`
- LLM generation: `garak` scan against `/query` with `RAG_USE_LLM=1` (non-blocking weekly/manual, artifact `garak-llm-summary`) via `.github/workflows/llm-generation-security.yml`

## Tests
Preferred (scripted):
```bash
./scripts/launch_backend_tests.sh
```

Manual:
```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

## Evaluation (Promptfoo)
Run a minimal golden-query evaluation (answer/citations/policy checks):
```bash
cd backend
RAG_AUTH_DISABLED=1 uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:
```bash
./scripts/run_promptfoo_eval.sh
```

Node runtime note:
- `promptfoo` in this repo expects Node.js `>= 20.10` (recommended `22.x`).
- If you see a syntax error around `with {type: 'json'}`, your Node version is too old.

Output artifact:
- `artifacts/promptfoo/results.json`

CI gate:
- `promptfoo-eval` is blocking and validates result artifact integrity/pass status via `scripts/check_promptfoo_results.py`.

## Query Security Scan (Garak Baseline)
Run a minimal garak baseline scan against the local `/query` endpoint in retrieval mode:
```bash
cd backend
source .venv/bin/activate
RAG_AUTH_DISABLED=1 RAG_USE_LLM=0 RAG_EMBEDDING_BACKEND=hash uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:
```bash
cd backend
source .venv/bin/activate
uv pip install "garak==0.13.2"
cd ..
./scripts/run_garak_scan.sh
```

Output artifacts (sanitized by default):
- `artifacts/garak/garak-summary.json`
- `artifacts/garak/rest_generator_options.json`
- `artifacts/garak/garak_run_config.yaml`

Notes:
- Raw garak reports are not persisted by default. Set `RAG_GARAK_KEEP_RAW_ARTIFACTS=1` only for local debugging.
- This baseline does not exercise LLM generation regressions because it runs with `RAG_USE_LLM=0`.

## LLM Generation Security Scan (Garak)
Run garak against the same `/query` endpoint with real LLM generation enabled:
```bash
cd backend
source .venv/bin/activate
uv pip install -e ".[dev,llm]"
RAG_AUTH_DISABLED=1 \
RAG_USE_LLM=1 \
RAG_EMBEDDING_BACKEND=hash \
RAG_LLM_MODEL_PATH=/absolute/path/to/model.gguf \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:
```bash
RAG_GARAK_ARTIFACT_DIR=artifacts/garak-llm \
RAG_GARAK_SUMMARY_FILE=artifacts/garak-llm/garak-summary.json \
./scripts/run_garak_scan.sh
```

Notes:
- Keep `RAG_GARAK_KEEP_RAW_ARTIFACTS=0` (default) to avoid persisting prompt/response transcripts.
- Model weights have separate licenses; verify and document the chosen model license.

## Demo Dataset
- Italian Wikipedia excerpts in `data/wikipedia_it/`
- Attribution: `data/ATTRIBUTION.md`
- Golden queries: `data/golden_queries.md`

## Roadmap (Short)
- Expand governance UI to surface policy-filtered retrieval behavior.
- Add dedicated evaluation scenarios for label-based policy enforcement.
- Extend security/eval tooling in CI.

## Notes
- This is a portfolio project: we prioritize clarity, security, and reproducibility over shortcuts.
- Only open-source and free tooling is used for core features.
