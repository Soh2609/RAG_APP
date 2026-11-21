"""Retrieval and vector search services package."""

from app.services.retrival.embeddings import (
    embed_batch,
    embed_query,
    embed_text,
    embed_texts,
    get_embedding_dim,
)
from app.services.retrival.qdrant import (
    ensure_collection,
    get_qdrant_client,
)
from app.services.retrival.retriever import (
    RetrievedChunk,
    RetrievalResult,
    SemanticRetriever,
    retrieve,
)

__all__ = [
    "embed_batch",
    "embed_query",
    "embed_text",
    "embed_texts",
    "get_embedding_dim",
    "get_qdrant_client",
    "ensure_collection",
    "RetrievedChunk",
    "RetrievalResult",
    "SemanticRetriever",
    "retrieve",
]
