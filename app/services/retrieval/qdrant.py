from pathlib import Path
from typing import Optional

import logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.core.exceptions import DimensionMismatchError, VectorIndexError
from app.services.retrieval.embeddings import get_embedding_dim, get_model_type

try:
    logfire.configure(service_name="qdrant-service", send_to_logfire="if-token-present")
except Exception:
    pass

_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Lazily initializes and returns a singleton QdrantClient with fail-safe controls."""
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
            if not settings.qdrant_allow_local_fallback:
                raise VectorIndexError(
                    f"Remote Qdrant connection failed and QDRANT_ALLOW_LOCAL_FALLBACK=False: {e}"
                ) from e
            logfire.warning(
                f"Remote Qdrant cluster connection failed: {e}. "
                "Falling back to local embedded Qdrant storage at './data/qdrant_storage'."
            )

    if not settings.qdrant_allow_local_fallback and (not settings.qdrant_url or not settings.qdrant_url.startswith("http")):
        raise VectorIndexError(
            "No remote Qdrant URL configured and QDRANT_ALLOW_LOCAL_FALLBACK=False."
        )

    local_storage_path = Path("data") / "qdrant_storage"
    local_storage_path.mkdir(parents=True, exist_ok=True)
    _qdrant_client = QdrantClient(path=str(local_storage_path))
    logfire.info(f"Initialized local embedded Qdrant storage at {local_storage_path}")
    return _qdrant_client


def resolve_collection_name(base_collection: Optional[str] = None) -> str:
    """Derives a model-partitioned collection name to prevent dimension collisions.

    If base_collection is explicitly given and already contains a dimension/model tag,
    it is returned as-is. Otherwise, appends the model suffix (e.g. '_gemini_3072' or '_st_768').
    """
    base = base_collection or settings.qdrant_collection
    model_type = get_model_type()
    dim = get_embedding_dim()

    suffix = f"_{model_type}_{dim}"
    if base.endswith(suffix):
        return base

    # If base already has an explicit custom tag like test_col, keep it
    if base != settings.qdrant_collection:
        return base

    return f"{base}{suffix}"


def ensure_collection(
    client: QdrantClient,
    collection_name: Optional[str] = None,
    recreate: bool = False,
) -> str:
    """Ensures target Qdrant collection exists with proper dimensions and indices.

    Validates that existing collections match the active embedding model's dimensions.
    Returns the resolved collection name.
    """
    col_name = collection_name or resolve_collection_name()
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
            # Create payload indices for fast filtering during retrieval
            for field_name in ("source_type", "source_file"):
                try:
                    client.create_payload_index(
                        collection_name=col_name,
                        field_name=field_name,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                except Exception as e:
                    logfire.warning(
                        f"Could not create payload index on '{col_name}' for '{field_name}': {e}"
                    )
            logfire.info(f"Collection '{col_name}' initialized successfully with payload indices")
        else:
            # Hard Dimension Guard: Assert stored collection vector dimension matches active model
            try:
                info = client.get_collection(col_name)
                vectors_config = info.config.params.vectors
                stored_dim = getattr(vectors_config, "size", None)
                if stored_dim is not None and stored_dim != vector_dim:
                    raise DimensionMismatchError(
                        f"DIMENSION MISMATCH: Collection '{col_name}' was configured for {stored_dim}-dim vectors, "
                        f"but active embedding model produces {vector_dim}-dim vectors. "
                        f"Please re-embed or use the appropriate model collection."
                    )
            except DimensionMismatchError:
                raise
            except Exception as e:
                logfire.debug(f"Could not inspect collection config details for {col_name}: {e}")

            logfire.info(f"Collection '{col_name}' already exists and is dimensionally valid ({vector_dim}d)")

        return col_name
