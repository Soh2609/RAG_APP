import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    qdrant_url = os.getenv("Qdrant_Cluster_Endpoint")
    qdrant_api_key = os.getenv("Qdrant_Api_Key")
    qdrant_collection = "enterprise_rag"

    groq_api_key = os.getenv("groq_api_key")
    groq_model = "llama-3.3-70b-versatile"

settings = Settings()
