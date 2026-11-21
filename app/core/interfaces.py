"""Abstract interfaces and protocols for decoupling RAG pipeline components."""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class DocumentLoader(Protocol):
    """Protocol for document loaders."""
    def __call__(self, file_path: str) -> str:
        ...


@runtime_checkable
class EmbeddingService(Protocol):
    """Protocol for embedding providers."""
    def embed_query(self, query: str) -> List[float]:
        ...

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...

    def get_embedding_dim(self) -> int:
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector databases."""
    def upsert(self, collection_name: str, points: List[Any], wait: bool = True) -> Any:
        ...

    def search(self, *args: Any, **kwargs: Any) -> Any:
        ...
