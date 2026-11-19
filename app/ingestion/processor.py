import os
import uuid
import json , sys, logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.services.retrival.embeddings import embed_text, get_embedding_dim
from app.ingestion.loaders.pdf import parse_pdf
from app.ingestion.loaders.text import parse_text
from app.ingestion.loaders.html import parse_html
from app.ingestion.loaders.office import parse_office
from app.ingestion.chunking.splitter import chunk_text

logfire.configure(service_name="ingestion-service")

processed_data_dir = "processed_data"

#initialize qdrant client
qdrant_client = QdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key
)

def save_processed_locally(data: dict, source_type:str, filename: str) -> str:
    """
    save parsed chunk metadata as json in processed_data/<source_type>/
    """
    pass

def process_file(file_path: str, filename : str, source_type: str):
    """
    Parse -> chunk -> save locally -> embed -> index in Qdrant"""
    pass

def process_directory(dir_path: str, source_type: str):
    """
    process every file in directory"""
    pass

def run_universal_ingestion(base_dir:str, explicit_source_type: str= None, wipe: bool = False):
    """
    Scan base_dir, map sub folder to souce types and  ingest all documents.
    pass --wipe to drop and recreate the qdrant collection before ingestion"""

    