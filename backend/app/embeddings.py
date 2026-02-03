from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable

import numpy as np
from sentence_transformers import SentenceTransformer

_DEFAULT_MODEL = "intfloat/multilingual-e5-small"


def default_model_name() -> str:
    return os.getenv("RAG_EMBEDDING_MODEL", _DEFAULT_MODEL)


@lru_cache(maxsize=1)
def get_embedder(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def embed_texts(texts: Iterable[str], model_name: str | None = None) -> np.ndarray:
    model = get_embedder(model_name or default_model_name())
    return model.encode(list(texts), normalize_embeddings=True)


def embed_text(text: str, model_name: str | None = None) -> np.ndarray:
    model = get_embedder(model_name or default_model_name())
    return model.encode(text, normalize_embeddings=True)
