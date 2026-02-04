from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return repo_root() / "data"


def wikipedia_it_dir() -> Path:
    return data_dir() / "wikipedia_it"


def store_backend() -> str:
    return os.getenv("RAG_STORE", "memory")


def database_url() -> str:
    return os.getenv(
        "RAG_DATABASE_URL",
        "postgresql+psycopg://rag:rag@localhost:5432/rag",
    )


def embedding_dim() -> int:
    return int(os.getenv("RAG_EMBEDDING_DIM", "384"))


def cors_origins() -> list[str]:
    origins = os.getenv("RAG_CORS_ORIGINS")
    if origins:
        return [origin.strip() for origin in origins.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
