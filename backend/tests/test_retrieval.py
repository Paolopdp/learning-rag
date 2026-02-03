import numpy as np

from app.models import Chunk
from app.retrieval import top_k_chunks


def test_top_k_chunks_orders_by_score() -> None:
    chunks = [
        Chunk(
            document_id="doc1",
            content="alpha",
            start_char=0,
            end_char=5,
            chunk_index=0,
            source_title="Doc 1",
            source_url=None,
        ),
        Chunk(
            document_id="doc2",
            content="beta",
            start_char=0,
            end_char=4,
            chunk_index=0,
            source_title="Doc 2",
            source_url=None,
        ),
    ]
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
    query_embedding = np.array([0.9, 0.1])

    results = top_k_chunks(chunks, embeddings, query_embedding, top_k=2)

    assert results[0].chunk.content == "alpha"
    assert results[1].chunk.content == "beta"
