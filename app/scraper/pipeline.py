import argparse
import json
from typing import Any, Dict, Optional

import logfire

from app.ingestion.processor import ensure_collection, get_qdrant_client, process_directory
from app.scraper.crawler import CrawlSummary, DocumentationCrawler

try:
    logfire.configure(service_name="scraper-service", send_to_logfire="if-token-present")
except Exception:
    pass


def scrape_and_ingest(
    start_url: str,
    output_dir: Optional[str] = None,
    max_pages: int = 50,
    max_depth: int = 3,
    delay: float = 0.5,
    allowed_prefix: Optional[str] = None,
    auto_ingest: bool = True,
    wipe: bool = False,
    source_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Orchestrates end-to-end web scraping and vector database ingestion:

    1. Crawls documentation starting at start_url (BFS).
    2. Stores HTML files and manifest.json into data/scraped/<domain>.
    3. If auto_ingest is True, runs Phase 1 ingestion processor on scraped pages,
       embedding chunks and upserting into Qdrant.
    """
    with logfire.span("Scrape and Ingest Pipeline", url=start_url, auto_ingest=auto_ingest):
        # Step 1: Execute web crawl
        crawler = DocumentationCrawler(
            start_url=start_url,
            output_dir=output_dir,
            max_pages=max_pages,
            max_depth=max_depth,
            delay=delay,
            allowed_prefix=allowed_prefix,
        )

        crawl_summary: CrawlSummary = crawler.crawl()

        pipeline_report: Dict[str, Any] = {
            "crawl_summary": {
                "start_url": crawl_summary.start_url,
                "domain": crawl_summary.domain,
                "total_pages_scraped": crawl_summary.total_pages_scraped,
                "total_failed": crawl_summary.total_failed,
                "output_dir": crawl_summary.output_dir,
                "manifest_path": crawl_summary.manifest_path,
                "elapsed_seconds": crawl_summary.elapsed_seconds,
            },
            "ingestion_summary": None,
        }

        # Step 2: Ingest into Qdrant if requested
        if auto_ingest and crawl_summary.total_pages_scraped > 0:
            logfire.info(f"Triggering automatic vector ingestion for {crawl_summary.output_dir}...")
            client = get_qdrant_client()
            ensure_collection(client, recreate=wipe)

            tag = source_type or f"web_{crawl_summary.domain}"
            ingestion_res = process_directory(
                dir_path=crawl_summary.output_dir,
                source_type=tag,
            )
            pipeline_report["ingestion_summary"] = ingestion_res

        return pipeline_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Web Scraper and Ingestion Pipeline")
    parser.add_argument("--url", type=str, required=True, help="Target start URL to crawl")
    parser.add_argument("--max-pages", type=int, default=20, help="Maximum number of pages to scrape")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum crawl depth from start URL")
    parser.add_argument("--delay", type=float, default=0.5, help="Polite delay in seconds between requests")
    parser.add_argument("--prefix", type=str, default=None, help="Restrict crawl to URL path prefix (e.g., /docs/)")
    parser.add_argument("--output-dir", type=str, default=None, help="Custom output directory")
    parser.add_argument("--source-type", type=str, default=None, help="Custom Qdrant source_type tag")
    parser.add_argument("--no-ingest", action="store_true", help="Only scrape without vector ingestion")
    parser.add_argument("--wipe", action="store_true", help="Wipe Qdrant collection before ingestion")

    args = parser.parse_args()

    report = scrape_and_ingest(
        start_url=args.url,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=args.delay,
        allowed_prefix=args.prefix,
        auto_ingest=not args.no_ingest,
        wipe=args.wipe,
        source_type=args.source_type,
    )

    print(json.dumps(report, indent=2))
