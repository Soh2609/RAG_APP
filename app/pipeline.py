import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

import logfire

from app.config import settings
from app.ingestion.processor import (
    LOADER_MAP,
    PROCESSED_DATA_DIR,
    ensure_collection,
    get_qdrant_client,
    process_file,
)
from app.scraper.crawler import CrawlSummary, DocumentationCrawler
from app.scraper.url_utils import get_domain

try:
    logfire.configure(service_name="pipeline-orchestrator", send_to_logfire="if-token-present")
except Exception:
    pass


@dataclass
class Stage1Result:
    """Encapsulates output of Stage 1: Data Acquisition / Extraction."""
    source: str
    staging_dir: str
    total_files: int
    manifest_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    status: str = "success"


@dataclass
class Stage2Result:
    """Encapsulates output of Stage 2: Processing, Chunking & Vector Indexing."""
    collection_name: str
    source_type: str
    total_documents: int
    successful: int
    skipped: int
    errors: int
    details: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    status: str = "success"


@dataclass
class PipelineResult:
    """Unified result for the end-to-end two-stage pipeline."""
    pipeline_id: str
    stage_1: Stage1Result
    stage_2: Optional[Stage2Result] = None
    total_elapsed_seconds: float = 0.0
    status: str = "success"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TwoStagePipeline:
    """Enterprise RAG Pipeline Orchestrator.

    Decouples Data Acquisition (Stage 1) from Processing & Vector Indexing (Stage 2)
    while offering high-level linked execution methods and incremental change detection.
    """

    def __init__(self, collection_name: Optional[str] = None):
        self.collection_name = collection_name or settings.qdrant_collection

    def run_web_pipeline(
        self,
        url: str,
        max_pages: int = 50,
        max_depth: int = 3,
        delay: float = 0.5,
        allowed_prefix: Optional[str] = None,
        output_dir: Optional[str] = None,
        source_type: Optional[str] = None,
        auto_index: bool = True,
        incremental: bool = True,
        wipe: bool = False,
    ) -> PipelineResult:
        """Executes Stage 1 (web crawl) followed optionally by Stage 2 (vector indexing)."""
        pipeline_id = f"pipe_{uuid.uuid4().hex[:8]}"
        t0 = time.time()

        with logfire.span("Two-Stage Web Pipeline", pipeline_id=pipeline_id, url=url):
            # ---------------------------------------------------------
            # Stage 1: Data Acquisition (Web Crawl & Staging)
            # ---------------------------------------------------------
            s1_t0 = time.time()
            crawler = DocumentationCrawler(
                start_url=url,
                output_dir=output_dir,
                max_pages=max_pages,
                max_depth=max_depth,
                delay=delay,
                allowed_prefix=allowed_prefix,
            )
            crawl_summary: CrawlSummary = crawler.crawl()
            s1_elapsed = time.time() - s1_t0

            stage1_res = Stage1Result(
                source="web_crawler",
                staging_dir=crawl_summary.output_dir,
                total_files=crawl_summary.total_pages_scraped,
                manifest_path=crawl_summary.manifest_path,
                metadata={
                    "start_url": crawl_summary.start_url,
                    "domain": crawl_summary.domain,
                    "failed_pages": crawl_summary.total_failed,
                },
                elapsed_seconds=round(s1_elapsed, 2),
                status="success" if crawl_summary.total_pages_scraped > 0 else "empty",
            )

            # ---------------------------------------------------------
            # Stage 2: Processing & Indexing (if requested)
            # ---------------------------------------------------------
            stage2_res = None
            if auto_index and stage1_res.total_files > 0:
                tag = source_type or f"web_{crawl_summary.domain}"
                stage2_res = self.index_staged_directory(
                    staged_dir=crawl_summary.output_dir,
                    source_type=tag,
                    incremental=incremental,
                    wipe=wipe,
                )

            total_elapsed = time.time() - t0
            pipeline_status = "success"
            if stage2_res and stage2_res.errors > 0:
                pipeline_status = "completed_with_errors"
            elif stage1_res.status == "empty":
                pipeline_status = "stage_1_empty"
            elif not auto_index:
                pipeline_status = "stage_1_only"

            return PipelineResult(
                pipeline_id=pipeline_id,
                stage_1=stage1_res,
                stage_2=stage2_res,
                total_elapsed_seconds=round(total_elapsed, 2),
                status=pipeline_status,
            )

    def run_local_pipeline(
        self,
        dir_path: str,
        source_type: Optional[str] = None,
        auto_index: bool = True,
        incremental: bool = True,
        wipe: bool = False,
    ) -> PipelineResult:
        """Executes Stage 1 (local directory validation/staging) followed by Stage 2 (indexing)."""
        pipeline_id = f"pipe_{uuid.uuid4().hex[:8]}"
        t0 = time.time()
        path_obj = Path(dir_path)

        if not path_obj.exists() or not path_obj.is_dir():
            raise NotADirectoryError(f"Directory not found: {dir_path}")

        with logfire.span("Two-Stage Local Pipeline", pipeline_id=pipeline_id, dir=str(dir_path)):
            # Stage 1: Local Discovery
            s1_t0 = time.time()
            supported_files = [
                p for p in path_obj.rglob("*")
                if p.is_file() and p.suffix.lower() in LOADER_MAP
            ]
            s1_elapsed = time.time() - s1_t0

            stage1_res = Stage1Result(
                source="local_directory",
                staging_dir=str(path_obj.resolve()),
                total_files=len(supported_files),
                metadata={"base_dir": str(dir_path)},
                elapsed_seconds=round(s1_elapsed, 2),
                status="success" if supported_files else "empty",
            )

            # Stage 2: Processing & Indexing
            stage2_res = None
            if auto_index and stage1_res.total_files > 0:
                tag = source_type or path_obj.name
                stage2_res = self.index_staged_directory(
                    staged_dir=str(path_obj),
                    source_type=tag,
                    incremental=incremental,
                    wipe=wipe,
                )

            total_elapsed = time.time() - t0
            return PipelineResult(
                pipeline_id=pipeline_id,
                stage_1=stage1_res,
                stage_2=stage2_res,
                total_elapsed_seconds=round(total_elapsed, 2),
                status="success" if not (stage2_res and stage2_res.errors > 0) else "completed_with_errors",
            )

    def index_staged_directory(
        self,
        staged_dir: str,
        source_type: str = "generic",
        incremental: bool = True,
        wipe: bool = False,
    ) -> Stage2Result:
        """Stage 2 Engine: Ingests documents from a pre-staged directory into Qdrant.

        Supports incremental change detection to skip re-embedding unchanged documents.
        """
        path_obj = Path(staged_dir)
        s2_t0 = time.time()

        with logfire.span("Stage 2 Indexing", dir=staged_dir, source_type=source_type, incremental=incremental):
            client = get_qdrant_client()
            ensure_collection(client, collection_name=self.collection_name, recreate=wipe)

            # Discover all supported documents
            files_to_process: List[Path] = []
            for root, dirs, files in os.walk(path_obj):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv")]
                for f in files:
                    p = Path(root) / f
                    if p.suffix.lower() in LOADER_MAP:
                        files_to_process.append(p)

            results: List[Dict[str, Any]] = []
            successful = 0
            skipped = 0
            errors = 0

            # Load existing cached hashes if incremental indexing is active
            cached_hashes: Dict[str, str] = {}
            if incremental and not wipe:
                cached_hashes = self._load_existing_hashes(source_type)

            for file_path in files_to_process:
                try:
                    # Incremental check: read file content hash
                    if incremental and not wipe:
                        file_hash = self._compute_quick_hash(file_path)
                        stem = file_path.stem
                        if cached_hashes.get(stem) == file_hash:
                            logfire.info(f"Skipping unchanged document (hash match): {file_path.name}")
                            skipped += 1
                            results.append({
                                "status": "skipped_unchanged",
                                "file": file_path.name,
                                "hash": file_hash,
                            })
                            continue

                    res = process_file(
                        file_path=str(file_path),
                        filename=file_path.name,
                        source_type=source_type,
                    )
                    results.append(res)
                    if res.get("status") == "success":
                        successful += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors += 1
                    logfire.error(f"Error indexing {file_path.name}", error=str(e))
                    results.append({
                        "status": "error",
                        "file": file_path.name,
                        "error": str(e),
                    })

            s2_elapsed = time.time() - s2_t0
            return Stage2Result(
                collection_name=self.collection_name,
                source_type=source_type,
                total_documents=len(files_to_process),
                successful=successful,
                skipped=skipped,
                errors=errors,
                details=results,
                elapsed_seconds=round(s2_elapsed, 2),
                status="success" if errors == 0 else "completed_with_errors",
            )

    def _load_existing_hashes(self, source_type: str) -> Dict[str, str]:
        """Loads cached SHA-256 hashes from existing local artifacts in processed_data/<source_type>/."""
        hashes: Dict[str, str] = {}
        target_dir = PROCESSED_DATA_DIR / source_type
        if not target_dir.exists():
            return hashes

        for json_file in target_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "file_hash" in data:
                        hashes[json_file.stem] = data["file_hash"]
            except Exception:
                continue
        return hashes

    def _compute_quick_hash(self, file_path: Path) -> str:
        """Computes a SHA-256 hash of a file's raw bytes for incremental change detection."""
        import hashlib
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()


# Singleton pipeline instance for convenient import
pipeline = TwoStagePipeline()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Two-Stage Enterprise RAG Pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", type=str, help="Stage 1: Documentation website URL to crawl")
    group.add_argument("--dir", type=str, help="Stage 1: Local directory of documents to ingest")

    # Stage controls
    parser.add_argument("--stage-1-only", action="store_true", help="Execute Stage 1 only (Acquisition & Staging)")
    parser.add_argument("--stage-2-only", action="store_true", help="Execute Stage 2 only on an existing staged directory")
    parser.add_argument("--source-type", type=str, default=None, help="Custom Qdrant source_type tag")

    # Crawler options
    parser.add_argument("--max-pages", type=int, default=20, help="Maximum pages to scrape")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum crawl depth")
    parser.add_argument("--delay", type=float, default=0.5, help="Polite delay between requests (seconds)")
    parser.add_argument("--prefix", type=str, default=None, help="Crawl path prefix constraint")
    parser.add_argument("--output-dir", type=str, default=None, help="Custom staging directory")

    # Ingestion options
    parser.add_argument("--no-incremental", action="store_true", help="Disable hash-based incremental skipping")
    parser.add_argument("--wipe", action="store_true", help="Wipe Qdrant collection before indexing")

    args = parser.parse_args()

    orchestrator = TwoStagePipeline()

    if args.url:
        result = orchestrator.run_web_pipeline(
            url=args.url,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            delay=args.delay,
            allowed_prefix=args.prefix,
            output_dir=args.output_dir,
            source_type=args.source_type,
            auto_index=not args.stage_1_only,
            incremental=not args.no_incremental,
            wipe=args.wipe,
        )
    elif args.dir and args.stage_2_only:
        tag = args.source_type or Path(args.dir).name
        res_s2 = orchestrator.index_staged_directory(
            staged_dir=args.dir,
            source_type=tag,
            incremental=not args.no_incremental,
            wipe=args.wipe,
        )
        result = PipelineResult(
            pipeline_id=f"pipe_s2_{uuid.uuid4().hex[:8]}",
            stage_1=Stage1Result(source="pre_staged_dir", staging_dir=args.dir, total_files=res_s2.total_documents),
            stage_2=res_s2,
            total_elapsed_seconds=res_s2.elapsed_seconds,
            status=res_s2.status,
        )
    else:
        result = orchestrator.run_local_pipeline(
            dir_path=args.dir,
            source_type=args.source_type,
            auto_index=not args.stage_1_only,
            incremental=not args.no_incremental,
            wipe=args.wipe,
        )

    print(json.dumps(result.to_dict(), indent=2))
