import random
import time
from typing import List, Optional

import logfire
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import settings
from app.core.exceptions import EmbeddingError

batch_size = 50
_gemini_dim = 3072
_fallback_dim = 768  # all-mpnet-base-v2

_active_model = None
_model_type: Optional[str] = None


def _probe_gemini() -> Optional[GoogleGenerativeAIEmbeddings]:
    """Tries one embed call to verify Gemini is reachable. Returns model or None."""
    if not settings.gemini_api_key:
        return None

    try:
        model = GoogleGenerativeAIEmbeddings(
            model=settings.gemini_embedding_model,
            google_api_key=settings.gemini_api_key,
        )
        model.embed_query("probe")
        logfire.info(f"Gemini embeddings ready ({settings.gemini_embedding_model}, 3072-dim).")
        return model
    except Exception as e:
        logfire.warning(f"Gemini probe failed ({e}). Will check fallback policy.")
        return None


def _load_fallback():
    """Loads SentenceTransformer fallback model."""
    from sentence_transformers import SentenceTransformer

    logfire.info(f"Loading sentence-transformers '{settings.fallback_embedding_model}' locally (768-dim)")
    return SentenceTransformer(settings.fallback_embedding_model)


def _init() -> None:
    """Initializes the active embedding model respecting fallback configuration."""
    global _active_model, _model_type

    if _active_model is not None:
        return

    gemini = _probe_gemini()
    if gemini:
        _active_model = gemini
        _model_type = "gemini"
        return
    elif settings.allow_embedding_fallback:
        logfire.warning(
            "⚠️ EMBEDDING FALLBACK ACTIVATED: Using local SentenceTransformers (768d). "
            "Vectors will be segregated from Gemini-indexed collections."
        )
        _active_model = _load_fallback()
        _model_type = "fallback"
    else:
        raise EmbeddingError(
            "Gemini probe failed and ALLOW_EMBEDDING_FALLBACK is disabled. "
            "Configure a valid GEMINI_API_KEY or enable fallback explicitly."
        )


def get_embedding_dim() -> int:
    """Returns the vector dimension for the active model."""
    _init()
    return _gemini_dim if _model_type == "gemini" else _fallback_dim


def get_model_type() -> str:
    """Returns the active model identifier ('gemini' or 'fallback')."""
    _init()
    return _model_type or "unknown"


def get_active_model_name() -> str:
    """Returns the exact model name/version currently loaded."""
    _init()
    if _model_type == "gemini":
        return settings.gemini_embedding_model
    return settings.fallback_embedding_model


def embed_batch(batch: List[str]) -> List[List[float]]:
    """Embeds a batch of texts with retry, backoff, and jitter."""
    _init()
    if not batch:
        return []

    if _model_type == "gemini":
        for attempt in range(4):
            try:
                return _active_model.embed_documents(batch)
            except Exception as e:
                err = str(e).lower()
                is_rate_limit = any(
                    x in err for x in ("429", "rate", "quota", "resource_exhausted")
                )
                if is_rate_limit and attempt < 3:
                    # Exponential backoff with uniform random jitter
                    wait = (2 ** attempt) + random.uniform(0.1, 0.9)
                    logfire.warning(
                        f"Gemini rate limit hit - retrying in {wait:.2f}s ({attempt + 1}/4)."
                    )
                    time.sleep(wait)
                else:
                    logfire.error("Failed to embed with Gemini after retries")
                    raise EmbeddingError(f"Gemini embedding failed: {e}") from e

        raise EmbeddingError("Gemini rate limit persisted after 4 attempts")
    else:
        return _active_model.encode(batch, show_progress_bar=False).tolist()


def embed_query(query: str) -> List[float]:
    """Embeds a single query string for semantic retrieval."""
    _init()
    if not query or not isinstance(query, str) or not query.strip():
        raise ValueError("Query string cannot be empty")

    if _model_type == "gemini":
        return _active_model.embed_query(query.strip())
    else:
        return _active_model.encode([query.strip()])[0].tolist()


def embed_text(text: str) -> List[float]:
    """Convenience alias for embedding a single text string."""
    return embed_query(text)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embeds a list of texts in chunks of batch_size."""
    _init()
    if not texts:
        return []

    all_embeddings: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        with logfire.span("Embed Batch", model=_model_type, start=i, size=len(batch)):
            all_embeddings.extend(embed_batch(batch))

    return all_embeddings
