import os

import pytest

# Ensure stable backend defaults before test modules import app.main.
os.environ.setdefault("RAG_STORE", "memory")
os.environ.setdefault("RAG_EMBEDDING_BACKEND", "hash")
os.environ.setdefault("RAG_USE_LLM", "0")
os.environ.setdefault("RAG_AUTH_DISABLED", "1")
os.environ.setdefault("RAG_OTEL_ENABLED", "0")
os.environ.setdefault("RAG_QUERY_RATE_LIMIT_ENABLED", "0")
os.environ.setdefault("RAG_AUTH_LOGIN_RATE_LIMIT_ENABLED", "0")
os.environ.setdefault("RAG_INGEST_RATE_LIMIT_ENABLED", "0")


@pytest.fixture(autouse=True)
def _default_test_env(monkeypatch) -> None:
    monkeypatch.setenv("RAG_STORE", "memory")
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RAG_USE_LLM", "0")
    monkeypatch.setenv("RAG_AUTH_DISABLED", "1")
    monkeypatch.setenv("RAG_OTEL_ENABLED", "0")
    monkeypatch.setenv("RAG_QUERY_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("RAG_AUTH_LOGIN_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("RAG_INGEST_RATE_LIMIT_ENABLED", "0")
