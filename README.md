# RAG Assistant (Governance & Security by Design)

[![CI](https://github.com/Paolopdp/learning-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/Paolopdp/learning-rag/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Paolopdp/learning-rag/actions/workflows/codeql.yml/badge.svg)](https://github.com/Paolopdp/learning-rag/actions/workflows/codeql.yml)

Local-first, open-source RAG system focused on **secure-by-default** AI application engineering. This repo is intentionally learning-first, built in small vertical slices with KISS/Clean Code/TDD where applicable.

## Status
- Backend MVP skeleton is live (auth + workspaces + citations).
- First vertical slice: ingest -> chunk -> embed -> retrieve -> answer with citations.
- Minimal frontend UI is available (auth, ingest/query, citations, audit log).

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

# Ingest the demo dataset (replace WORKSPACE_ID + TOKEN)
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

# List workspaces
curl -H "Authorization: Bearer TOKEN" http://127.0.0.1:8000/workspaces
```

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

## Auth Configuration
Environment variables:
- `RAG_JWT_SECRET` (required in production; default is dev-only)
- `RAG_AUTH_DISABLED=1` to bypass auth (tests/dev only)
- `RAG_CORS_ORIGINS` to override allowed origins (comma-separated)

## CI Security Checks
The CI pipeline runs:
- `gitleaks` (secret scanning)
- `osv-scanner` (dependency vulnerabilities)
- `trivy` (filesystem scan)
- `syft` (SBOM generation)

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

## Demo Dataset
- Italian Wikipedia excerpts in `data/wikipedia_it/`
- Attribution: `data/ATTRIBUTION.md`
- Golden queries: `data/golden_queries.md`

## Roadmap (Short)
- Add document inventory + classification labels.
- Expand audit log UI and governance views.
- Add basic workspace member management UI.
- Extend security/eval tooling in CI.

## Notes
- This is a portfolio project: we prioritize clarity, security, and reproducibility over shortcuts.
- Only open-source and free tooling is used for core features.
