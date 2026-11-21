import argparse
from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Dict, List, Optional, Union

import logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.services.retrival.embeddings import embed_query, get_embedding_dim
from app.services.retrival.qdrant import get_qdrant_client

try:
    logfire.configure(service_name="retrieval-service", send_to_logfire="if-token-present")
except Exception:
    pass


@dataclass
class RetrievedChunk:
    """Represents a single retrieved document chunk with similarity score and full provenance."""
    chunk_id: str
    text: str
    score: float
    source_file: str
    source_path: str
    source_type: str
    chunk_index: int = 0
    total_chunks: int = 1
    file_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    """Encapsulates the complete search result for a query."""
    query: str
    chunks: List[RetrievedChunk]
    total_found: int
    latency_ms: float
    applied_filters: Dict[str, Any] = field(default_factory=dict)
    embedding_dim: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "total_found": self.total_found,
            "latency_ms": self.latency_ms,
            "applied_filters": self.applied_filters,
            "embedding_dim": self.embedding_dim,
            "chunks": [c.to_dict() for c in self.chunks],
        }


def build_qdrant_filter(
    source_type: Optional[Union[str, List[str]]] = None,
    source_file: Optional[Union[str, List[str]]] = None,
    custom_conditions: Optional[List[models.Condition]] = None,
) -> Optional[models.Filter]:
    """Constructs a Qdrant native models.Filter from optional metadata constraints."""
    conditions: List[models.Condition] = []

    # Handle source_type filtering (single string or list)
    if source_type:
        if isinstance(source_type, list):
            if len(source_type) == 1:
                conditions.append(
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value=source_type[0]),
                    )
                )
            elif len(source_type) > 1:
                conditions.append(
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchAny(any=source_type),
                    )
                )
        else:
            conditions.append(
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchValue(value=source_type),
                )
            )

    # Handle source_file filtering (single string or list)
    if source_file:
        if isinstance(source_file, list):
            if len(source_file) == 1:
                conditions.append(
                    models.FieldCondition(
                        key="source_file",
                        match=models.MatchValue(value=source_file[0]),
                    )
                )
            elif len(source_file) > 1:
                conditions.append(
                    models.FieldCondition(
                        key="source_file",
                        match=models.MatchAny(any=source_file),
                    )
                )
        else:
            conditions.append(
                models.FieldCondition(
                    key="source_file",
                    match=models.MatchValue(value=source_file),
                )
            )

    if custom_conditions:
        conditions.extend(custom_conditions)

    return models.Filter(must=conditions) if conditions else None


class SemanticRetriever:
    """Production-grade Semantic Retriever for Qdrant.

    Embeds queries using the configured embedding engine (Gemini with SentenceTransformers fallback),
    applies native pre-filtering on metadata payloads, and ranks results by vector similarity.
    """

    def __init__(
        self,
        collection_name: Optional[str] = None,
        client: Optional[QdrantClient] = None,
    ):
        self.collection_name = collection_name or settings.qdrant_collection
        self._client = client

    def get_client(self) -> QdrantClient:
        """Lazily acquires the Qdrant client."""
        if self._client is None:
            self._client = get_qdrant_client()
        return self._client

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
        source_type: Optional[Union[str, List[str]]] = None,
        source_file: Optional[Union[str, List[str]]] = None,
        filter_conditions: Optional[models.Filter] = None,
    ) -> RetrievalResult:
        """Retrieves top-k relevant chunks from Qdrant matching the query and filters."""
        if not query or not isinstance(query, str) or not query.strip():
            raise ValueError("Query string cannot be empty")

        cleaned_query = query.strip()
        t0 = time.time()

        with logfire.span("Semantic Retrieval", query=cleaned_query, top_k=top_k):
            # 1. Embed query
            query_vector = embed_query(cleaned_query)
            dim = len(query_vector)

            # 2. Build metadata filter
            query_filter = filter_conditions or build_qdrant_filter(
                source_type=source_type,
                source_file=source_file,
            )

            client = self.get_client()

            # 3. Query Qdrant (supporting query_points and fallback search)
            raw_points: List[Any] = []
            if hasattr(client, "query_points"):
                response = client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                    with_payload=True,
                )
                raw_points = response.points
            elif hasattr(client, "search"):
                raw_points = client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                    with_payload=True,
                )

            # 4. Map raw points into structured RetrievedChunk DTOs
            retrieved_chunks: List[RetrievedChunk] = []
            for pt in raw_points:
                payload = pt.payload or {}
                chunk = RetrievedChunk(
                    chunk_id=str(pt.id),
                    text=payload.get("text", ""),
                    score=float(pt.score) if pt.score is not None else 0.0,
                    source_file=payload.get("source_file", "unknown"),
                    source_path=payload.get("source_path", ""),
                    source_type=payload.get("source_type", "unknown"),
                    chunk_index=payload.get("chunk_index", 0),
                    total_chunks=payload.get("total_chunks", 1),
                    file_hash=payload.get("file_hash", ""),
                    metadata={
                        k: v
                        for k, v in payload.items()
                        if k not in (
                            "text", "source_file", "source_path", "source_type",
                            "chunk_index", "total_chunks", "file_hash"
                        )
                    },
                )
                retrieved_chunks.append(chunk)

            elapsed_ms = round((time.time() - t0) * 1000, 2)

            applied_filters_summary: Dict[str, Any] = {}
            if source_type:
                applied_filters_summary["source_type"] = source_type
            if source_file:
                applied_filters_summary["source_file"] = source_file
            if score_threshold is not None:
                applied_filters_summary["score_threshold"] = score_threshold

            result = RetrievalResult(
                query=cleaned_query,
                chunks=retrieved_chunks,
                total_found=len(retrieved_chunks),
                latency_ms=elapsed_ms,
                applied_filters=applied_filters_summary,
                embedding_dim=dim,
            )

            logfire.info(
                f"Retrieved {len(retrieved_chunks)} chunks in {elapsed_ms}ms for query: '{cleaned_query[:60]}...'"
            )
            return result


# Singleton default retriever instance
retriever = SemanticRetriever()


def retrieve(
    query: str,
    top_k: int = 5,
    score_threshold: Optional[float] = None,
    source_type: Optional[Union[str, List[str]]] = None,
    source_file: Optional[Union[str, List[str]]] = None,
) -> RetrievalResult:
    """Convenience function for global semantic retrieval."""
    return retriever.retrieve(
        query=query,
        top_k=top_k,
        score_threshold=score_threshold,
        source_type=source_type,
        source_file=source_file,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semantic Vector Search for RAG")
    parser.add_argument("--query", type=str, required=True, help="Natural language query string")
    parser.add_argument("--top-k", type=int, default=5, help="Number of top relevant chunks to retrieve")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum cosine similarity score cutoff")
    parser.add_argument("--source-type", type=str, default=None, help="Filter results by source_type (e.g. web_docs)")
    parser.add_argument("--source-file", type=str, default=None, help="Filter results by source_file name")
    parser.add_argument("--collection", type=str, default=None, help="Custom Qdrant collection name")

    args = parser.parse_args()

    custom_retriever = SemanticRetriever(collection_name=args.collection)
    res = custom_retriever.retrieve(
        query=args.query,
        top_k=args.top_k,
        score_threshold=args.min_score,
        source_type=args.source_type,
        source_file=args.source_file,
    )

    print(json.dumps(res.to_dict(), indent=2))
