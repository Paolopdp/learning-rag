# RAG Assistant (Governance & Security by Design)

Local-first, open-source RAG system focused on **secure-by-default** AI application engineering. This repo is intentionally learning-first, built in small vertical slices with KISS/Clean Code/TDD where applicable.

## Status
- Backend MVP skeleton is live.
- First vertical slice: ingest -> chunk -> embed -> retrieve -> answer with citations (no auth yet).
- Frontend is not implemented yet.

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
```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Postgres + pgvector (Optional but Recommended)
Start the database:
```bash
docker compose up -d db
```

Run migrations:
```bash
cd backend
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
alembic upgrade head
```

Enable Postgres storage:
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
# Ingest the demo dataset
curl -X POST http://127.0.0.1:8000/ingest/demo

# Ask a question (extractive answer + citations)
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Che cos’è SPID e a cosa serve?", "top_k": 3}'

# Preview stored chunks
curl "http://127.0.0.1:8000/chunks?limit=3"
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

## Tests
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
- Retrieval integration test using golden queries.
- Add auth + workspaces.
- Observability + audit logging.
- Security/eval tooling in CI.

## Notes
- This is a portfolio project: we prioritize clarity, security, and reproducibility over shortcuts.
- Only open-source and free tooling is used for core features.
