from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Iterable

import numpy as np
from sentence_transformers import SentenceTransformer

_DEFAULT_MODEL = "intfloat/multilingual-e5-small"


def default_model_name() -> str:
    return os.getenv("RAG_EMBEDDING_MODEL", _DEFAULT_MODEL)


def embedding_backend() -> str:
    return os.getenv("RAG_EMBEDDING_BACKEND", "sentence-transformers")


@lru_cache(maxsize=1)
def get_embedder(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def _hash_dim() -> int:
    return int(os.getenv("RAG_HASH_DIM", "256"))


def _token_index(token: str, dim: int) -> int:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") % dim


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in cleaned.split() if token]


def _hash_embed(texts: Iterable[str]) -> np.ndarray:
    texts = list(texts)
    if not texts:
        return np.array([])

    dim = _hash_dim()
    vectors: list[np.ndarray] = []
    for text in texts:
        vec = np.zeros(dim, dtype=float)
        for token in _tokenize(text):
            vec[_token_index(token, dim)] += 1.0
        vec = vec / (np.linalg.norm(vec) + 1e-12)
        vectors.append(vec)
    return np.vstack(vectors)


def embed_texts(texts: Iterable[str], model_name: str | None = None) -> np.ndarray:
    texts = list(texts)
    if not texts:
        return np.array([])
    backend = embedding_backend()
    if backend == "hash":
        return _hash_embed(texts)
    model = get_embedder(model_name or default_model_name())
    return model.encode(texts, normalize_embeddings=True)


def embed_text(text: str, model_name: str | None = None) -> np.ndarray:
    backend = embedding_backend()
    if backend == "hash":
        return _hash_embed([text])[0]
    model = get_embedder(model_name or default_model_name())
    return model.encode(text, normalize_embeddings=True)
