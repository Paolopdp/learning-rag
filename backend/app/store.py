from __future__ import annotations

from dataclasses import dataclass, field
import uuid

import numpy as np
from sqlalchemy import delete, select

from app.config import store_backend
from app.db import SessionLocal
from app.models import Chunk, Document
from app.retrieval import RetrievalResult, top_k_chunks
from app.sql_models import ChunkORM, DocumentORM


@dataclass
class InMemoryChunkStore:
    chunks: list[Chunk] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)

    def clear(self) -> None:
        self.chunks.clear()
        self.embeddings.clear()

    def add_many(
        self,
        documents: list[Document],
        new_chunks: list[Chunk],
        new_embeddings: np.ndarray,
    ) -> None:
        if len(new_chunks) != len(new_embeddings):
            raise ValueError("Chunks and embeddings must be the same length.")
        self.chunks.extend(new_chunks)
        if len(new_chunks) == 0:
            return
        self.embeddings.extend([embedding.tolist() for embedding in new_embeddings])

    def all(self, limit: int | None = None) -> list[Chunk]:
        if limit is None:
            return list(self.chunks)
        return list(self.chunks[:limit])

    def embedding_matrix(self) -> np.ndarray:
        if not self.embeddings:
            return np.array([])
        return np.array(self.embeddings)

    def search(self, query_embedding: np.ndarray, top_k: int = 3) -> list[RetrievalResult]:
        return top_k_chunks(self.chunks, self.embedding_matrix(), query_embedding, top_k=top_k)


@dataclass
class PostgresChunkStore:
    def clear(self) -> None:
        with SessionLocal() as session:
            session.execute(delete(ChunkORM))
            session.execute(delete(DocumentORM))
            session.commit()

    def add_many(
        self,
        documents: list[Document],
        new_chunks: list[Chunk],
        new_embeddings: np.ndarray,
    ) -> None:
        if len(new_chunks) != len(new_embeddings):
            raise ValueError("Chunks and embeddings must be the same length.")

        if not documents and not new_chunks:
            return

        with SessionLocal() as session:
            doc_map: dict[uuid.UUID, DocumentORM] = {}
            for doc in documents:
                doc_id = uuid.UUID(doc.document_id)
                doc_map[doc_id] = DocumentORM(
                    id=doc_id,
                    title=doc.title,
                    source_url=doc.source_url,
                    license=doc.license,
                    accessed_at=doc.accessed_at,
                    text=doc.text,
                )
            session.add_all(doc_map.values())
            session.flush()

            for chunk, embedding in zip(new_chunks, new_embeddings):
                session.add(
                    ChunkORM(
                        id=uuid.UUID(chunk.chunk_id),
                        document_id=uuid.UUID(chunk.document_id),
                        chunk_index=chunk.chunk_index,
                        start_char=chunk.start_char,
                        end_char=chunk.end_char,
                        content=chunk.content,
                        embedding=embedding.tolist(),
                        source_title=chunk.source_title,
                        source_url=chunk.source_url,
                    )
                )
            session.commit()

    def all(self, limit: int | None = None) -> list[Chunk]:
        with SessionLocal() as session:
            stmt = select(ChunkORM)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [self._to_chunk(row) for row in rows]

    def search(self, query_embedding: np.ndarray, top_k: int = 3) -> list[RetrievalResult]:
        if query_embedding.size == 0:
            return []
        query_vec = query_embedding.tolist()
        with SessionLocal() as session:
            distance = ChunkORM.embedding.cosine_distance(query_vec)
            stmt = (
                select(ChunkORM, distance.label("distance"))
                .order_by(distance)
                .limit(top_k)
            )
            results = session.execute(stmt).all()
            output: list[RetrievalResult] = []
            for row, dist in results:
                score = 1.0 - float(dist)
                output.append(RetrievalResult(chunk=self._to_chunk(row), score=score))
            return output

    @staticmethod
    def _to_chunk(row: ChunkORM) -> Chunk:
        return Chunk(
            document_id=str(row.document_id),
            content=row.content,
            start_char=row.start_char,
            end_char=row.end_char,
            chunk_index=row.chunk_index,
            source_title=row.source_title,
            source_url=row.source_url,
            chunk_id=str(row.id),
        )


def get_chunk_store():
    backend = store_backend()
    if backend == "postgres":
        return PostgresChunkStore()
    return InMemoryChunkStore()
