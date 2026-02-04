from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import cors_origins, wikipedia_it_dir
from app.embeddings import embed_text, embed_texts
from app.ingestion import chunk_documents, load_documents_from_dir
from app.llm import generate_answer, llm_enabled
from app.store import get_chunk_store

app = FastAPI(title="RAG Backend", version="0.1.0")

chunk_store = get_chunk_store()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest/demo")
def ingest_demo() -> dict[str, int]:
    documents = load_documents_from_dir(wikipedia_it_dir())
    chunks = chunk_documents(documents)
    embeddings = embed_texts([chunk.content for chunk in chunks])
    chunk_store.clear()
    chunk_store.add_many(documents, chunks, embeddings)
    return {"documents": len(documents), "chunks": len(chunks)}


@app.get("/chunks")
def list_chunks(limit: int = 5) -> list[dict[str, str | int | None]]:
    items = chunk_store.all(limit=limit)
    return [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "source_title": chunk.source_title,
            "source_url": chunk.source_url,
        }
        for chunk in items
    ]


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class Citation(BaseModel):
    chunk_id: str
    source_title: str
    source_url: str | None
    score: float
    excerpt: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    if not chunk_store.all(limit=1):
        raise HTTPException(status_code=400, detail="No data ingested yet.")

    query_embedding = embed_text(request.question)
    results = chunk_store.search(query_embedding, top_k=request.top_k)

    if not results:
        return QueryResponse(answer="Nessun risultato.", citations=[])

    top_chunks = [result.chunk for result in results]
    if llm_enabled():
        try:
            answer = generate_answer(request.question, top_chunks)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        answer = top_chunks[0].content
    citations = [
        Citation(
            chunk_id=result.chunk.chunk_id,
            source_title=result.chunk.source_title,
            source_url=result.chunk.source_url,
            score=result.score,
            excerpt=result.chunk.content[:200],
        )
        for result in results
    ]
    return QueryResponse(answer=answer, citations=citations)
