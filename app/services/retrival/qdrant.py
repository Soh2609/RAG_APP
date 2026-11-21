from pathlib import Path
from typing import Optional

import logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.services.retrival.embeddings import get_embedding_dim

try:
    logfire.configure(service_name="qdrant-service", send_to_logfire="if-token-present")
except Exception:
    pass

_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Lazily initializes and returns a singleton QdrantClient.

    Attempts to connect to the remote Qdrant cluster if configured. If the remote
    cluster is unreachable (e.g. cluster suspended, connection reset, or offline),
    it gracefully falls back to local embedded Qdrant storage at './data/qdrant_storage'
    so development and testing are never blocked.
    """
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client

    if settings.qdrant_url and settings.qdrant_url.startswith("http"):
        try:
            client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
                timeout=5.0,
            )
            # Lightweight probe to check if cluster is online and reachable
            client.get_collections()
            logfire.info(f"Connected to remote Qdrant cluster at {settings.qdrant_url}")
            _qdrant_client = client
            return _qdrant_client
        except Exception as e:
            logfire.warning(
                f"Remote Qdrant cluster connection failed: {e}. "
                "Falling back to local embedded Qdrant storage at './data/qdrant_storage'."
            )

    local_storage_path = Path("data") / "qdrant_storage"
    local_storage_path.mkdir(parents=True, exist_ok=True)
    _qdrant_client = QdrantClient(path=str(local_storage_path))
    logfire.info(f"Initialized local embedded Qdrant storage at {local_storage_path}")
    return _qdrant_client


def ensure_collection(
    client: QdrantClient,
    collection_name: Optional[str] = None,
    recreate: bool = False,
) -> None:
    """Ensures the target Qdrant collection exists with proper dimensions and indices.

    If recreate=True, existing collection will be dropped and recreated.
    """
    col_name = collection_name or settings.qdrant_collection
    vector_dim = get_embedding_dim()

    with logfire.span("Ensure Qdrant collection", collection=col_name, dim=vector_dim, recreate=recreate):
        exists = client.collection_exists(col_name)

        if exists and recreate:
            logfire.info(f"Dropping existing collection '{col_name}' as wipe requested")
            client.delete_collection(col_name)
            exists = False

        if not exists:
            logfire.info(f"Creating collection '{col_name}' with {vector_dim}-dim vectors")
            client.create_collection(
                collection_name=col_name,
                vectors_config=models.VectorParams(
                    size=vector_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            # Create payload indices for fast filtering during retrieval (on remote Qdrant)
            try:
                client.create_payload_index(
                    collection_name=col_name,
                    field_name="source_type",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                client.create_payload_index(
                    collection_name=col_name,
                    field_name="source_file",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass
            logfire.info(f"Collection '{col_name}' initialized successfully with payload indices")
        else:
            logfire.info(f"Collection '{col_name}' already exists and is ready")
