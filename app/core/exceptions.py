"""Domain exception hierarchy for the Enterprise RAG application."""

class RAGError(Exception):
    """Base exception for all RAG application errors."""
    pass


class ParseError(RAGError):
    """Raised when parsing or reading a document fails."""
    pass


class EmbeddingError(RAGError):
    """Raised when text embedding fails or model is unavailable."""
    pass


class DimensionMismatchError(RAGError):
    """Raised when vector dimension does not match collection configuration."""
    pass


class VectorIndexError(RAGError):
    """Raised when indexing, connecting, or querying the vector database fails."""
    pass


class CrawlError(RAGError):
    """Raised when crawling or fetching a web resource encounters an error."""
    pass


class SSRFSecurityError(CrawlError):
    """Raised when a URL targets a restricted, private, loopback, or link-local address."""
    pass
