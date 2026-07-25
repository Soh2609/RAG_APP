import time
import logfire
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.config import settings

batch_size = 50
_gemini_dim = 3072
_fallback_dim = 768 #all-mpnet-base-v2

_active_model = None
_model_type : str | None = None

def _probe_gemini():
    """
    Try one embed call to verify Gemini is reachable. returns model or none"""

    try:
        model = GoogleGenerativeAIEmbeddings(
            model = "models/gemini-embedding-2-preview",
            google_api_key = settings.gemini_api_key
        )
        model.embed_query("probe")
        logfire.info("Gemini embeddings ready(gemini-embedding-2-preview, 3072-dim).")
        return model
    except Exception as e:
        logfire.warning(f"gemini probe failed. will use sentence transformer fallback.")
        return None

def _load_fallback():
    from sentence_transformers import SentenceTransformer
    logfire.info("loading sentence-transformers 'all-mpnet-base-v2' locally (768-dim)")
    return SentenceTransformer('all-mpnet-base-v2')
    
def _init():
    global _active_model, _model_type

    if _active_model is not None:
        return
    
    gemini = _probe_gemini()
    if gemini:
        _active_model = gemini
        _model_type = "gemini"
        return 
    else:
        _active_model = _load_fallback()
        _model_type = "fallback"

def get_embedding_dim() -> int:
    """ return the vector dimension for active model"""
    _init()
    return _gemini_dim if _model_type == "gemini" else _fallback_dim


def embed_batch(batch: list[str]) -> list[list[float]]:
    """
    embed a batch of texts
    """
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
                    wait = 2**attempt
                    logfire.warning(
                        f"Gemini rate limit hit - retrying in {wait}s "
                        f"({attempt + 1}/4)."
                    )
                    time.sleep(wait)
                else:
                    logfire.error("failed to embed with gemini after retries")
                    raise e

        raise RuntimeError("Gemini rate limit persisted after 4 attempts")
    else:
        return _active_model.encode(batch, show_progress_bar=False).tolist()


def embed_query(query:str) -> list[float]:
    _init()
    if _model_type == "gemini":
        return _active_model.embed_query(query)
    else:
        return _active_model.encode([query])[0].tolist()

def embed_texts(texts: list[str]) -> list[list[float]]:
    _init()
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        with logfire.span("Embed Batch", model= _model_type, start=i, size=len(batch)):
            all_embeddings.extend(embed_batch(batch)) 

