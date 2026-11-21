from dataclasses import dataclass, field
import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import logfire
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import settings
from app.scraper.url_utils import clean_url, is_safe_url

try:
    logfire.configure(service_name="scraper-service", send_to_logfire="if-token-present")
except Exception:
    pass


@dataclass
class FetchResult:
    """Encapsulates the raw HTTP response from fetching a web page."""
    url: str
    status_code: int
    html: str = ""
    content_type: str = ""
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300 and not self.error


@dataclass
class ExtractedPage:
    """Represents structured content and links parsed from a page."""
    url: str
    title: str = ""
    text: str = ""
    cleaned_html: str = ""
    links: List[str] = field(default_factory=list)


class PageFetcher:
    """Robust HTTP page fetcher with connection pooling, retries,
    custom user-agent, SSRF protection, and body size limits.
    """

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        user_agent: str = "EnterpriseRAG-Crawler/1.0 (+https://github.com/Soh2609/RAG_APP)",
        enforce_ssrf_check: bool = True,
    ):
        self.timeout = timeout
        self.enforce_ssrf_check = enforce_ssrf_check
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

        # Configure retry strategy with exponential backoff on transient errors
        retries = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def fetch(self, url: str) -> FetchResult:
        """Fetches a URL, enforces SSRF and size guards, validates content-type, and returns a FetchResult."""
        t0 = time.time()

        # -------------------------------------------------------------
        # SSRF Protection: Pre-flight DNS validation before HTTP dispatch
        # -------------------------------------------------------------
        if self.enforce_ssrf_check and not is_safe_url(url):
            logfire.warning(f"SSRF Protection blocked request to unsafe/private address: {url}")
            return FetchResult(
                url=url,
                status_code=403,
                elapsed_seconds=time.time() - t0,
                error="SSRF Protection: Target URL resolves to private, loopback, or cloud-metadata network",
            )

        try:
            with logfire.span("HTTP Fetch", url=url):
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True, stream=True)
                elapsed = time.time() - t0
                final_url = clean_url(response.url)

                # Re-verify post-redirect destination for SSRF
                if self.enforce_ssrf_check and not is_safe_url(final_url):
                    logfire.warning(f"SSRF Protection blocked redirect to unsafe address: {final_url}")
                    return FetchResult(
                        url=final_url,
                        status_code=403,
                        elapsed_seconds=elapsed,
                        error="SSRF Protection: Redirect led to restricted IP address",
                    )

                content_type = response.headers.get("Content-Type", "").lower()

                # Verify content type is HTML
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    return FetchResult(
                        url=final_url,
                        status_code=response.status_code,
                        content_type=content_type,
                        elapsed_seconds=elapsed,
                        error=f"Non-HTML content type: {content_type}",
                    )

                # Enforce body size limit from Content-Length header if provided
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > settings.max_http_body_bytes:
                            return FetchResult(
                                url=final_url,
                                status_code=413,
                                content_type=content_type,
                                elapsed_seconds=elapsed,
                                error=f"Response body exceeds limit ({content_length} bytes > {settings.max_http_body_bytes})",
                            )
                    except ValueError:
                        pass

                body_text = response.text or ""
                # Enforce size limit on decoded content
                if len(body_text.encode("utf-8", errors="ignore")) > settings.max_http_body_bytes:
                    return FetchResult(
                        url=final_url,
                        status_code=413,
                        content_type=content_type,
                        elapsed_seconds=elapsed,
                        error=f"Body exceeds limit of {settings.max_http_body_bytes} bytes",
                    )

                return FetchResult(
                    url=final_url,
                    status_code=response.status_code,
                    html=body_text,
                    content_type=content_type,
                    elapsed_seconds=elapsed,
                )
        except requests.exceptions.Timeout:
            return FetchResult(
                url=url,
                status_code=408,
                elapsed_seconds=time.time() - t0,
                error="Request timed out",
            )
        except Exception as e:
            return FetchResult(
                url=url,
                status_code=0,
                elapsed_seconds=time.time() - t0,
                error=str(e),
            )


def extract_page_data(html: str, current_url: str) -> ExtractedPage:
    """Parses raw HTML, extracts title, outgoing links, and cleaned text/HTML.

    Strips script, style, navigation boilerplate, and cookie banners to avoid chunk pollution.
    """
    if not html:
        return ExtractedPage(url=current_url)

    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract Title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)

    # 2. Extract and resolve outgoing links
    discovered_links: List[str] = []
    seen: set = set()

    for a_tag in soup.find_all("a", href=True):
        raw_href = a_tag["href"].strip()
        if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        resolved_url = urljoin(current_url, raw_href)
        cleaned = clean_url(resolved_url)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            discovered_links.append(cleaned)

    # 3. Clean noise and boilerplate elements
    for noise_tag in ("script", "style", "noscript", "svg", "meta"):
        for el in soup(noise_tag):
            el.decompose()

    # Boilerplate removal: navigation, footers, sidebars, cookie banners
    boilerplate_selectors = [
        "nav", "header", "footer", "aside",
        ".sidebar", ".cookie-banner", ".nav-bar",
        "[role='navigation']", "[aria-label='breadcrumb']",
    ]
    for selector in boilerplate_selectors:
        for match in soup.select(selector):
            match.decompose()

    # Extract clean text
    raw_text = soup.get_text(separator="\n")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    cleaned_text = "\n\n".join(lines)

    return ExtractedPage(
        url=current_url,
        title=title,
        text=cleaned_text,
        cleaned_html=str(soup),
        links=discovered_links,
    )
