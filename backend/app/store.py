from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.models import Chunk


@dataclass
class InMemoryChunkStore:
    chunks: list[Chunk] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)

    def clear(self) -> None:
        self.chunks.clear()
        self.embeddings.clear()

    def add_many(self, new_chunks: list[Chunk], new_embeddings: np.ndarray) -> None:
        if len(new_chunks) != len(new_embeddings):
            raise ValueError("Chunks and embeddings must be the same length.")
        self.chunks.extend(new_chunks)
        self.embeddings.extend([embedding.tolist() for embedding in new_embeddings])

    def all(self, limit: int | None = None) -> list[Chunk]:
        if limit is None:
            return list(self.chunks)
        return list(self.chunks[:limit])

    def embedding_matrix(self) -> np.ndarray:
        if not self.embeddings:
            return np.array([])
        return np.array(self.embeddings)
