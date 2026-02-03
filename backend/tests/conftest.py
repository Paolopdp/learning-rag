import os

import pytest


@pytest.fixture(autouse=True)
def _default_test_env(monkeypatch) -> None:
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RAG_USE_LLM", "0")
