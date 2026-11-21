from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Enterprise RAG Application Settings with startup validation and environment binding."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Keys & Endpoints (support multiple case variants)
    gemini_api_key: Optional[str] = Field(default=None, validation_alias="GEMINI_API_KEY")
    qdrant_url: Optional[str] = Field(default=None, validation_alias="Qdrant_Cluster_Endpoint")
    qdrant_api_key: Optional[str] = Field(default=None, validation_alias="Qdrant_Api_Key")
    qdrant_collection: str = Field(default="enterprise_rag", validation_alias="QDRANT_COLLECTION")

    groq_api_key: Optional[str] = Field(default=None, validation_alias="groq_api_key")
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL")

    # Safety & Fallback Controls
    allow_embedding_fallback: bool = Field(default=True, validation_alias="ALLOW_EMBEDDING_FALLBACK")
    qdrant_allow_local_fallback: bool = Field(default=True, validation_alias="QDRANT_ALLOW_LOCAL_FALLBACK")

    # Resource & Security Limits
    max_file_size_bytes: int = Field(default=50 * 1024 * 1024, validation_alias="MAX_FILE_SIZE_BYTES")  # 50 MB
    max_http_body_bytes: int = Field(default=10 * 1024 * 1024, validation_alias="MAX_HTTP_BODY_BYTES")  # 10 MB

    # Model Configuration & Pinning
    gemini_embedding_model: str = Field(
        default="models/gemini-embedding-2-preview",
        validation_alias="GEMINI_EMBEDDING_MODEL",
    )
    fallback_embedding_model: str = Field(
        default="all-mpnet-base-v2",
        validation_alias="FALLBACK_EMBEDDING_MODEL",
    )


settings = Settings()
