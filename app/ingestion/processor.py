import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
import uuid

import logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.ingestion.chunking.splitter import chunk_text
from app.ingestion.loaders import parse_html, parse_office, parse_pdf, parse_text
from app.services.retrieval.embeddings import (
    embed_texts,
    get_active_model_name,
    get_embedding_dim,
    get_model_type,
)
from app.services.retrieval.qdrant import (
    ensure_collection,
    get_qdrant_client,
    resolve_collection_name,
)

try:
    logfire.configure(service_name="ingestion-service", send_to_logfire="if-token-present")
except Exception:
    pass

PROCESSED_DATA_DIR = Path("processed_data")

# Supported file extensions mapped to their corresponding parser
LOADER_MAP = {
    ".pdf": parse_pdf,
    ".html": parse_html,
    ".htm": parse_html,
    ".txt": parse_text,
    ".md": parse_text,
    ".markdown": parse_text,
    ".docx": parse_office,
    ".doc": parse_office,
    ".pptx": parse_office,
    ".ppt": parse_office,
}


def save_processed_locally(data: Dict[str, Any], source_type: str, filename: str) -> str:
    """Saves parsed chunks and metadata as formatted JSON in processed_data/<source_type>/."""
    target_dir = PROCESSED_DATA_DIR / source_type
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = Path(filename).stem
    out_path = target_dir / f"{safe_stem}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logfire.info(f"Saved local artifact to {out_path}")
    return str(out_path)


def process_file(
    file_path: str,
    filename: Optional[str] = None,
    source_type: str = "generic",
    collection_name: Optional[str] = None,
    upsert_batch_size: int = 50,
) -> Dict[str, Any]:
    """Full ETL Pipeline for a single document:

    1. Enforce size limits
    2. Parse (via appropriate file loader)
    3. Chunk (with overlap and paragraph preservation)
    4. Save local metadata JSON for audit/cache
    5. Embed (Gemini or SentenceTransformers fallback)
    6. Purge prior vectors for this document (stale chunk prevention)
    7. Index/Upsert vectors into Qdrant with deterministic UUIDs and durability wait=True
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_name = filename or path_obj.name
    suffix = path_obj.suffix.lower()

    if suffix not in LOADER_MAP:
        logfire.warning(f"Unsupported file format '{suffix}' for {file_path}. Skipping.")
        return {"status": "skipped_unsupported", "file": file_name, "reason": f"unsupported suffix {suffix}"}

    # Pre-flight resource limit check
    file_size = path_obj.stat().st_size
    if file_size > settings.max_file_size_bytes:
        logfire.warning(
            f"File too large ({file_size} bytes, limit is {settings.max_file_size_bytes}): {file_name}. Skipping."
        )
        return {
            "status": "skipped_too_large",
            "file": file_name,
            "reason": f"file size {file_size} exceeds limit {settings.max_file_size_bytes}",
        }

    with logfire.span("Process file", file=file_name, source_type=source_type):
        loader = LOADER_MAP[suffix]
        raw_text = loader(str(path_obj))

        if not raw_text or not raw_text.strip():
            logfire.warning(f"Empty text parsed from {file_name}. Skipping indexing.")
            return {"status": "skipped_empty", "file": file_name, "reason": "empty extracted text"}

        file_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        chunks = chunk_text(raw_text)

        if not chunks:
            logfire.warning(f"No valid chunks generated for {file_name}.")
            return {"status": "skipped_no_chunks", "file": file_name}

        ingested_at = datetime.now(timezone.utc).isoformat()
        model_type = get_model_type()
        model_name = get_active_model_name()
        vector_dim = get_embedding_dim()

        chunk_records: List[Dict[str, Any]] = []

        for i, chunk in enumerate(chunks):
            # Deterministic point ID based on content hash & chunk index for idempotent updates
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_hash}:{i}"))
            chunk_records.append({
                "chunk_id": chunk_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "text": chunk,
                "char_count": len(chunk),
                "source_file": file_name,
                "source_path": str(path_obj.resolve()),
                "source_type": source_type,
                "file_hash": file_hash,
                "embedding_model": model_type,
                "embedding_model_name": model_name,
                "embedding_dim": vector_dim,
                "ingested_at": ingested_at,
            })

        # Save processed data locally for offline inspection/recovery
        local_artifact = save_processed_locally(
            data={
                "source_file": file_name,
                "source_type": source_type,
                "file_hash": file_hash,
                "total_chunks": len(chunks),
                "embedding_model": model_type,
                "embedding_model_name": model_name,
                "ingested_at": ingested_at,
                "chunks": chunk_records,
            },
            source_type=source_type,
            filename=file_name,
        )

        # Generate embeddings
        logfire.info(f"Generating embeddings for {len(chunks)} chunks from {file_name}...")
        embeddings = embed_texts(chunks)

        # Prepare Qdrant points
        points: List[models.PointStruct] = []
        for record, vector in zip(chunk_records, embeddings):
            points.append(
                models.PointStruct(
                    id=record["chunk_id"],
                    vector=vector,
                    payload=record,
                )
            )

        client = get_qdrant_client()
        col_name = ensure_collection(client, collection_name=collection_name)

        # ------------------------------------------------------------------
        # Scoped Purge: Delete existing chunks for this document to prevent
        # stale/duplicate vectors if the document content has been modified.
        # ------------------------------------------------------------------
        try:
            client.delete(
                collection_name=col_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source_file",
                                match=models.MatchValue(value=file_name),
                            )
                        ]
                    )
                ),
                wait=True,
            )
            logfire.debug(f"Purged previous vectors for {file_name} in '{col_name}'")
        except Exception as e:
            logfire.warning(f"Could not purge previous points for {file_name} in '{col_name}': {e}")

        # Upsert into Qdrant in batches with durability wait
        for i in range(0, len(points), upsert_batch_size):
            batch = points[i : i + upsert_batch_size]
            client.upsert(
                collection_name=col_name,
                points=batch,
                wait=True,
            )

        logfire.info(
            f"Successfully indexed {len(points)} points into Qdrant collection '{col_name}' for {file_name}"
        )

        return {
            "status": "success",
            "file": file_name,
            "source_type": source_type,
            "collection": col_name,
            "chunks": len(chunks),
            "file_hash": file_hash,
            "local_artifact": local_artifact,
        }


def _iter_supported_files(path_obj: Path) -> Iterator[Path]:
    """Generator streaming supported file paths without accumulating all files into memory."""
    for root, dirs, files in os.walk(path_obj):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", ".venv", "__pycache__")]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in LOADER_MAP:
                yield p


def process_directory(
    dir_path: str,
    source_type: str = "generic",
    collection_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Recursively processes every supported document in a given directory using generator streaming."""
    path_obj = Path(dir_path)
    if not path_obj.exists() or not path_obj.is_dir():
        raise NotADirectoryError(f"Directory not found: {dir_path}")

    with logfire.span("Process directory", dir=str(dir_path), source_type=source_type):
        results: List[Dict[str, Any]] = []
        success_count = 0
        skipped_count = 0
        error_count = 0
        total_files = 0

        for file_path in _iter_supported_files(path_obj):
            total_files += 1
            try:
                res = process_file(
                    file_path=str(file_path),
                    filename=file_path.name,
                    source_type=source_type,
                    collection_name=collection_name,
                )
                results.append(res)
                if res.get("status") == "success":
                    success_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                error_count += 1
                logfire.error(f"Error processing {file_path}", error=str(e))
                results.append({
                    "status": "error",
                    "file": file_path.name,
                    "error": str(e),
                })

        summary = {
            "directory": str(dir_path),
            "source_type": source_type,
            "total_files": total_files,
            "successful": success_count,
            "skipped": skipped_count,
            "errors": error_count,
            "results": results,
        }
        logfire.info(
            f"Directory processing complete: {total_files} files, {success_count} success, {error_count} errors"
        )
        return summary


def run_universal_ingestion(
    base_dir: str = "data",
    explicit_source_type: Optional[str] = None,
    collection_name: Optional[str] = None,
    wipe: bool = False,
) -> Dict[str, Any]:
    """Scans base_dir, automatically maps subdirectories to source_types,
    and ingests all documents into Qdrant.
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        base_path.mkdir(parents=True, exist_ok=True)
        logfire.info(f"Created base directory: {base_path}")

    client = get_qdrant_client()
    target_col = ensure_collection(client, collection_name=collection_name, recreate=wipe)

    with logfire.span("Universal ingestion", base_dir=str(base_dir), collection=target_col, wipe=wipe):
        subdirs = [d for d in base_path.iterdir() if d.is_dir() and not d.name.startswith(".")]

        summary_results: List[Dict[str, Any]] = []

        if subdirs:
            for subdir in subdirs:
                source_type = explicit_source_type or subdir.name
                res = process_directory(str(subdir), source_type=source_type, collection_name=target_col)
                summary_results.append(res)
        else:
            source_type = explicit_source_type or "general"
            res = process_directory(str(base_path), source_type=source_type, collection_name=target_col)
            summary_results.append(res)

        total_ingested = sum(r.get("successful", 0) for r in summary_results)
        total_errors = sum(r.get("errors", 0) for r in summary_results)

        final_report = {
            "base_dir": str(base_dir),
            "collection": target_col,
            "wipe": wipe,
            "subdirectories_processed": len(summary_results),
            "total_successful_documents": total_ingested,
            "total_errors": total_errors,
            "details": summary_results,
        }
        logfire.info(f"Universal ingestion finished: {total_ingested} indexed, {total_errors} errors")
        return final_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universal Document Ingestion for RAG")
    parser.add_argument("--base-dir", type=str, default="data", help="Root data directory to scan")
    parser.add_argument("--file", type=str, default=None, help="Process a single file directly")
    parser.add_argument("--source-type", type=str, default=None, help="Explicit source type tag")
    parser.add_argument("--collection", type=str, default=None, help="Custom Qdrant collection name")
    parser.add_argument("--wipe", action="store_true", help="Recreate Qdrant collection before ingestion")

    args = parser.parse_args()

    if args.file:
        st = args.source_type or "manual"
        res = process_file(args.file, source_type=st, collection_name=args.collection)
        print(json.dumps(res, indent=2))
    else:
        report = run_universal_ingestion(
            base_dir=args.base_dir,
            explicit_source_type=args.source_type,
            collection_name=args.collection,
            wipe=args.wipe,
        )
        print(json.dumps(report, indent=2))
