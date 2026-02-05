from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    documents: list[Document] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)

    def clear(self) -> None:
        self.documents.clear()
        self.chunks.clear()
        self.embeddings.clear()

    def clear_workspace(self, workspace_id: str) -> None:
        if not workspace_id:
            return
        self.documents = [
            document
            for document in self.documents
            if document.workspace_id != workspace_id
        ]
        filtered_chunks: list[Chunk] = []
        filtered_embeddings: list[list[float]] = []
        for chunk, embedding in zip(self.chunks, self.embeddings):
            if chunk.workspace_id != workspace_id:
                filtered_chunks.append(chunk)
                filtered_embeddings.append(embedding)
        self.chunks = filtered_chunks
        self.embeddings = filtered_embeddings

    def add_many(
        self,
        documents: list[Document],
        new_chunks: list[Chunk],
        new_embeddings: np.ndarray,
    ) -> None:
        if len(new_chunks) != len(new_embeddings):
            raise ValueError("Chunks and embeddings must be the same length.")
        for doc in documents:
            if not doc.workspace_id:
                raise ValueError("Document is missing workspace_id.")
        existing_ids = {document.document_id for document in documents}
        self.documents = [
            document
            for document in self.documents
            if document.document_id not in existing_ids
        ]
        self.documents.extend(documents)
        self.chunks.extend(new_chunks)
        if len(new_chunks) == 0:
            return
        self.embeddings.extend([embedding.tolist() for embedding in new_embeddings])

    def list_documents(self, workspace_id: str) -> list[Document]:
        return [
            document
            for document in self.documents
            if document.workspace_id == workspace_id
        ]

    def update_document_classification(
        self,
        workspace_id: str,
        document_id: str,
        classification_label: str,
    ) -> Document | None:
        for index, document in enumerate(self.documents):
            if (
                document.workspace_id == workspace_id
                and document.document_id == document_id
            ):
                updated = replace(document, classification_label=classification_label)
                self.documents[index] = updated
                return updated
        return None

    def all(self, limit: int | None = None) -> list[Chunk]:
        if limit is None:
            return list(self.chunks)
        return list(self.chunks[:limit])

    def has_workspace_data(self, workspace_id: str) -> bool:
        return any(chunk.workspace_id == workspace_id for chunk in self.chunks)

    def embedding_matrix(self) -> np.ndarray:
        if not self.embeddings:
            return np.array([])
        return np.array(self.embeddings)

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 3,
        workspace_id: str | None = None,
    ) -> list[RetrievalResult]:
        if workspace_id is None:
            return []
        indices = [
            index
            for index, chunk in enumerate(self.chunks)
            if chunk.workspace_id == workspace_id
        ]
        if not indices:
            return []
        filtered_chunks = [self.chunks[index] for index in indices]
        filtered_embeddings = np.array([self.embeddings[index] for index in indices])
        return top_k_chunks(filtered_chunks, filtered_embeddings, query_embedding, top_k=top_k)


@dataclass
class PostgresChunkStore:
    def clear(self) -> None:
        with SessionLocal() as session:
            session.execute(delete(ChunkORM))
            session.execute(delete(DocumentORM))
            session.commit()

    def clear_workspace(self, workspace_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                delete(ChunkORM).where(ChunkORM.workspace_id == uuid.UUID(workspace_id))
            )
            session.execute(
                delete(DocumentORM).where(
                    DocumentORM.workspace_id == uuid.UUID(workspace_id)
                )
            )
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
        if not documents and new_chunks:
            raise ValueError("Documents required when adding chunks.")

        with SessionLocal() as session:
            doc_map: dict[uuid.UUID, DocumentORM] = {}
            for doc in documents:
                if not doc.workspace_id:
                    raise ValueError("Document is missing workspace_id.")
                doc_id = uuid.UUID(doc.document_id)
                doc_map[doc_id] = DocumentORM(
                    id=doc_id,
                    workspace_id=uuid.UUID(doc.workspace_id),
                    title=doc.title,
                    source_url=doc.source_url,
                    license=doc.license,
                    accessed_at=doc.accessed_at,
                    text=doc.text,
                    classification_label=doc.classification_label,
                )
            session.add_all(doc_map.values())
            session.flush()

            for chunk, embedding in zip(new_chunks, new_embeddings):
                session.add(
                    ChunkORM(
                        id=uuid.UUID(chunk.chunk_id),
                        workspace_id=uuid.UUID(
                            chunk.workspace_id or documents[0].workspace_id
                        ),
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

    def list_documents(self, workspace_id: str) -> list[Document]:
        with SessionLocal() as session:
            rows = session.execute(
                select(DocumentORM)
                .where(DocumentORM.workspace_id == uuid.UUID(workspace_id))
                .order_by(DocumentORM.created_at.desc())
            ).scalars().all()
            return [self._to_document(row) for row in rows]

    def update_document_classification(
        self,
        workspace_id: str,
        document_id: str,
        classification_label: str,
    ) -> Document | None:
        with SessionLocal() as session:
            row = session.execute(
                select(DocumentORM).where(
                    DocumentORM.workspace_id == uuid.UUID(workspace_id),
                    DocumentORM.id == uuid.UUID(document_id),
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.classification_label = classification_label
            session.commit()
            session.refresh(row)
            return self._to_document(row)

    def all(self, limit: int | None = None) -> list[Chunk]:
        with SessionLocal() as session:
            stmt = select(ChunkORM)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [self._to_chunk(row) for row in rows]

    def has_workspace_data(self, workspace_id: str) -> bool:
        with SessionLocal() as session:
            stmt = (
                select(ChunkORM.id)
                .where(ChunkORM.workspace_id == uuid.UUID(workspace_id))
                .limit(1)
            )
            return session.execute(stmt).first() is not None

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 3,
        workspace_id: str | None = None,
    ) -> list[RetrievalResult]:
        if query_embedding.size == 0:
            return []
        if workspace_id is None:
            return []
        query_vec = query_embedding.tolist()
        with SessionLocal() as session:
            distance = ChunkORM.embedding.cosine_distance(query_vec)
            stmt = (
                select(ChunkORM, distance.label("distance"))
                .where(ChunkORM.workspace_id == uuid.UUID(workspace_id))
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
            workspace_id=str(row.workspace_id),
            content=row.content,
            start_char=row.start_char,
            end_char=row.end_char,
            chunk_index=row.chunk_index,
            source_title=row.source_title,
            source_url=row.source_url,
            chunk_id=str(row.id),
        )

    @staticmethod
    def _to_document(row: DocumentORM) -> Document:
        return Document(
            document_id=str(row.id),
            workspace_id=str(row.workspace_id),
            title=row.title,
            source_url=row.source_url,
            license=row.license,
            accessed_at=row.accessed_at,
            text=row.text,
            classification_label=row.classification_label,
        )


def get_chunk_store():
    backend = store_backend()
    if backend == "postgres":
        return PostgresChunkStore()
    return InMemoryChunkStore()
