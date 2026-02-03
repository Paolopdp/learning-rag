from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.models import Chunk


@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    score: float


def cosine_similarity_scores(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return np.array([])
    if vector.ndim != 1:
        vector = vector.reshape(-1)
    denom = np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector)
    denom = np.where(denom == 0, 1e-12, denom)
    return (matrix @ vector) / denom


def top_k_chunks(
    chunks: list[Chunk],
    embeddings: np.ndarray,
    query_embedding: np.ndarray,
    top_k: int = 3,
) -> list[RetrievalResult]:
    if not chunks or embeddings.size == 0:
        return []
    scores = cosine_similarity_scores(embeddings, query_embedding)
    top_k = max(1, min(top_k, len(chunks)))
    indices = np.argsort(scores)[::-1][:top_k]
    results: list[RetrievalResult] = []
    for idx in indices:
        results.append(RetrievalResult(chunk=chunks[int(idx)], score=float(scores[int(idx)])))
    return results
