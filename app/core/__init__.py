"""Core protocols, interfaces, and exceptions."""

from app.core.exceptions import (
    CrawlError,
    DimensionMismatchError,
    EmbeddingError,
    ParseError,
    RAGError,
    SSRFSecurityError,
    VectorIndexError,
)
from app.core.interfaces import DocumentLoader, EmbeddingService, VectorStore

__all__ = [
    "RAGError",
    "ParseError",
    "EmbeddingError",
    "DimensionMismatchError",
    "VectorIndexError",
    "CrawlError",
    "SSRFSecurityError",
    "DocumentLoader",
    "EmbeddingService",
    "VectorStore",
]
