from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
import urllib.robotparser
from urllib.parse import urlsplit

import logfire

from app.scraper.fetcher import ExtractedPage, FetchResult, PageFetcher, extract_page_data
from app.scraper.url_utils import (
    clean_url,
    get_domain,
    is_valid_crawl_target,
    url_to_filename,
)

try:
    logfire.configure(service_name="scraper-service", send_to_logfire="if-token-present")
except Exception:
    pass


@dataclass
class ScrapedPageMetadata:
    url: str
    title: str
    local_file: str
    content_hash: str
    depth: int
    char_count: int
    scraped_at: str
    status: str = "success"


@dataclass
class CrawlSummary:
    start_url: str
    domain: str
    total_pages_scraped: int
    total_failed: int
    output_dir: str
    manifest_path: str
    elapsed_seconds: float
    pages: List[Dict[str, Any]] = field(default_factory=list)


class DocumentationCrawler:
    """Breadth-First Search (BFS) documentation crawler with robots.txt compliance,
    SSRF protection, post-redirect scope enforcement, and atomic manifest persistence.
    """

    def __init__(
        self,
        start_url: str,
        output_dir: Optional[str] = None,
        max_pages: int = 50,
        max_depth: int = 3,
        delay: float = 0.5,
        allowed_prefix: Optional[str] = None,
        fetcher: Optional[PageFetcher] = None,
        respect_robots_txt: bool = True,
    ):
        self.start_url = clean_url(start_url)
        self.domain = get_domain(self.start_url)
        if not self.domain:
            raise ValueError(f"Invalid start URL: {start_url}")

        parts = urlsplit(self.start_url)
        self.scheme = parts.scheme or "https"

        # Default output directory: data/scraped/<domain>
        self.output_dir = Path(output_dir) if output_dir else Path("data") / "scraped" / self.domain
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.allowed_prefix = allowed_prefix
        self.fetcher = fetcher or PageFetcher()
        self.respect_robots_txt = respect_robots_txt

        # Robots.txt parser initialization
        self.robot_parser: Optional[urllib.robotparser.RobotFileParser] = None
        if self.respect_robots_txt:
            self._init_robots_txt()

        # State tracking
        self.queue: Deque[Tuple[str, int]] = deque([(self.start_url, 0)])
        self.visited: Set[str] = set()
        self.scraped_records: Dict[str, ScrapedPageMetadata] = {}
        self.failed_urls: Dict[str, str] = {}

    def _init_robots_txt(self) -> None:
        """Fetches and parses robots.txt for the target domain."""
        try:
            robots_url = f"{self.scheme}://{self.domain}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            # Use fetcher session headers for polite user-agent check
            user_agent = self.fetcher.session.headers.get("User-Agent", "*")
            rp.read()
            self.robot_parser = rp
            logfire.info(f"Initialized robots.txt parser for {robots_url}")

            # If host specifies a crawl delay, adopt it if higher than default
            crawl_delay = rp.crawl_delay(user_agent)
            if crawl_delay and crawl_delay > self.delay:
                logfire.info(f"Adopting robots.txt crawl-delay: {crawl_delay}s")
                self.delay = float(crawl_delay)
        except Exception as e:
            logfire.debug(f"Could not load robots.txt for {self.domain} ({e}). Proceeding with standard crawl limits.")
            self.robot_parser = None

    def _is_allowed_by_robots(self, url: str) -> bool:
        """Verifies if the URL is permitted by robots.txt."""
        if not self.respect_robots_txt or self.robot_parser is None:
            return True
        user_agent = self.fetcher.session.headers.get("User-Agent", "*")
        try:
            return self.robot_parser.can_fetch(user_agent, url)
        except Exception:
            return True

    def crawl(self) -> CrawlSummary:
        """Executes the BFS crawl loop with graceful interrupt handling."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()

        with logfire.span("Documentation Crawl", start_url=self.start_url, max_pages=self.max_pages):
            logfire.info(
                f"Starting BFS crawl on {self.start_url} (max_pages={self.max_pages}, max_depth={self.max_depth})"
            )

            try:
                while self.queue and len(self.scraped_records) < self.max_pages:
                    current_url, current_depth = self.queue.popleft()

                    if current_url in self.visited:
                        continue
                    self.visited.add(current_url)

                    # Robots.txt compliance check
                    if not self._is_allowed_by_robots(current_url):
                        logfire.info(f"Skipping {current_url} (disallowed by robots.txt)")
                        continue

                    logfire.info(
                        f"[{len(self.scraped_records) + 1}/{self.max_pages}] Crawling (depth={current_depth}): {current_url}"
                    )

                    fetch_res: FetchResult = self.fetcher.fetch(current_url)

                    if not fetch_res.is_success:
                        self.failed_urls[current_url] = fetch_res.error or f"HTTP {fetch_res.status_code}"
                        logfire.warning(f"Failed to fetch {current_url}: {self.failed_urls[current_url]}")
                        continue

                    # Post-redirect scope validation
                    if not is_valid_crawl_target(fetch_res.url, self.start_url, self.allowed_prefix):
                        logfire.warning(
                            f"Redirect destination out of scope: {current_url} -> {fetch_res.url}. Skipping."
                        )
                        continue

                    extracted: ExtractedPage = extract_page_data(fetch_res.html, fetch_res.url)

                    # Save raw/cleaned HTML to local file
                    filename = url_to_filename(extracted.url)
                    file_path = self.output_dir / filename

                    content_bytes = extracted.cleaned_html.encode("utf-8")
                    content_hash = hashlib.sha256(content_bytes).hexdigest()

                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(extracted.cleaned_html)

                    metadata = ScrapedPageMetadata(
                        url=extracted.url,
                        title=extracted.title,
                        local_file=str(file_path.resolve()),
                        content_hash=content_hash,
                        depth=current_depth,
                        char_count=len(extracted.text),
                        scraped_at=datetime.now(timezone.utc).isoformat(),
                        status="success",
                    )
                    self.scraped_records[extracted.url] = metadata

                    # Discover new links if within depth limits
                    if current_depth < self.max_depth:
                        for link in extracted.links:
                            if (
                                link not in self.visited
                                and is_valid_crawl_target(link, self.start_url, self.allowed_prefix)
                                and self._is_allowed_by_robots(link)
                            ):
                                self.queue.append((link, current_depth + 1))

                    # Polite delay between requests
                    if self.delay > 0:
                        time.sleep(self.delay)

            except KeyboardInterrupt:
                logfire.warning("Crawl interrupted by user. Finalizing and saving partial manifest.")
            finally:
                manifest_path = self._write_manifest()

            elapsed = time.time() - start_time

            summary = CrawlSummary(
                start_url=self.start_url,
                domain=self.domain,
                total_pages_scraped=len(self.scraped_records),
                total_failed=len(self.failed_urls),
                output_dir=str(self.output_dir.resolve()),
                manifest_path=str(manifest_path.resolve()),
                elapsed_seconds=round(elapsed, 2),
                pages=[asdict(m) for m in self.scraped_records.values()],
            )
            logfire.info(
                f"Crawl completed: {summary.total_pages_scraped} pages scraped in {summary.elapsed_seconds}s"
            )
            return summary

    def _write_manifest(self) -> Path:
        """Atomically writes or updates manifest.json using temporary staging file."""
        manifest_path = self.output_dir / "manifest.json"
        tmp_path = self.output_dir / "manifest.json.tmp"

        manifest_data = {
            "schema_version": "1.0",
            "start_url": self.start_url,
            "domain": self.domain,
            "last_crawled_at": datetime.now(timezone.utc).isoformat(),
            "total_pages": len(self.scraped_records),
            "total_failed": len(self.failed_urls),
            "pages": {url: asdict(meta) for url, meta in self.scraped_records.items()},
            "failed_urls": self.failed_urls,
        }

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        # Atomic rename/replace to prevent corruption on crash
        tmp_path.replace(manifest_path)
        return manifest_path
