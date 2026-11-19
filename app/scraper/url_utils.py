import os
import re
from typing import Optional, Set
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

# Tracking query parameters to strip for canonicalization
TRACKING_PARAMS: Set[str] = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "fbclid",
    "gclid",
    "msclkid",
}

# Binary and non-HTML static asset file extensions to ignore
EXCLUDED_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tiff",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".mkv", ".webm",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2",
    ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".msi",
    ".css", ".js", ".mjs", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".epub",  # PDFs are handled via ingestion loader directly if needed
}


def clean_url(url: str) -> str:
    """Canonicalizes and cleans a URL:

    1. Trims leading/trailing whitespace.
    2. Strips URL fragments (#hash).
    3. Normalizes scheme and host to lowercase.
    4. Strips marketing/tracking query parameters (utm_*, ref, etc.).
    5. Normalizes trailing slashes (preserves single root slash '/').
    """
    if not url or not isinstance(url, str):
        return ""

    url = url.strip()
    try:
        parts = urlsplit(url)
    except Exception:
        return ""

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    if not scheme or not netloc:
        return ""

    path = parts.path or "/"

    # Normalize trailing slash (collapse /path/ to /path, except root /)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Filter out tracking query parameters
    query = ""
    if parts.query:
        filtered_queries = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        if filtered_queries:
            query = urlencode(filtered_queries)

    # Reconstruct cleaned URL without fragment
    return urlunsplit((scheme, netloc, path, query, ""))


def get_domain(url: str) -> str:
    """Extracts lowercase netloc (domain + optional port) from a URL."""
    try:
        return urlsplit(url).netloc.lower()
    except Exception:
        return ""


def is_same_domain(url: str, base_url: str) -> bool:
    """Checks if a target URL belongs to the same domain as the base URL.

    Matches exact domain or subdomains of the base domain.
    """
    target_domain = get_domain(url)
    base_domain = get_domain(base_url)

    if not target_domain or not base_domain:
        return False

    return target_domain == base_domain or target_domain.endswith(f".{base_domain}")


def is_valid_crawl_target(
    url: str,
    base_url: str,
    allowed_prefix: Optional[str] = None,
) -> bool:
    """Validates whether a URL should be crawled:

    1. Valid HTTP/HTTPS scheme.
    2. Belongs to the same domain as base_url.
    3. Starts with allowed_prefix (if specified).
    4. Does not point to binary/static asset extensions.
    """
    if not url:
        return False

    try:
        parts = urlsplit(url)
    except Exception:
        return False

    if parts.scheme.lower() not in ("http", "https"):
        return False

    if not is_same_domain(url, base_url):
        return False

    path = parts.path or "/"

    # Check path prefix restriction if provided
    if allowed_prefix:
        norm_prefix = allowed_prefix.rstrip("/")
        if not path.startswith(norm_prefix):
            return False

    # Check for excluded file extensions
    _, ext = os.path.splitext(path.lower())
    if ext in EXCLUDED_EXTENSIONS:
        return False

    return True


def url_to_filename(url: str, ext: str = ".html") -> str:
    """Generates a safe filesystem filename from a URL path.

    Example:
        https://docs.example.com/api/v1/endpoints/ -> api_v1_endpoints.html
        https://docs.example.com/ -> index.html
    """
    try:
        parts = urlsplit(url)
        path = parts.path.strip("/")
        if not path:
            return f"index{ext}"

        # Replace path separators and illegal characters with underscores
        slug = re.sub(r'[\/\\:?"*<>|]+', "_", path)
        # Collapse multiple underscores
        slug = re.sub(r"_+", "_", slug).strip("_")

        if not slug:
            return f"index{ext}"

        # If slug already ends with the extension, don't double it
        if slug.lower().endswith(ext.lower()):
            return slug

        # Limit slug length for Windows filesystem limits (max ~200 chars)
        if len(slug) > 180:
            slug = slug[:180]

        return f"{slug}{ext}"
    except Exception:
        import uuid
        return f"page_{uuid.uuid4().hex[:8]}{ext}"
