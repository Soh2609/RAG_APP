import ipaddress
import os
import re
import socket
from typing import Optional, Set
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

# Tracking and crawl-trap query parameters to strip for canonicalization
STRIP_PARAMS: Set[str] = {
    # Marketing / Tracking
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
    # Session identifiers
    "jsessionid",
    "phpsessid",
    "aspsessionid",
    "sid",
}

# Binary and non-HTML static asset file extensions to ignore
EXCLUDED_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tiff",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".mkv", ".webm",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2",
    ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".msi",
    ".css", ".js", ".mjs", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".epub",
}

# SSRF Blocked CIDR ranges (Private, Loopback, Link-Local Cloud IMDS)
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # AWS/GCP Instance Metadata Service (IMDS)
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_safe_url(url: str) -> bool:
    """SSRF Protection Guard: Validates that a target URL does not resolve

    to loopback, private RFC-1918 networks, or cloud instance metadata (169.254.169.254).
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parts = urlsplit(url)
    except Exception:
        return False

    if parts.scheme.lower() not in ("http", "https"):
        return False

    hostname = parts.hostname
    if not hostname:
        return False

    # Block direct localhost and known metadata names
    if hostname.lower() in ("localhost", "metadata.google.internal", "instance-data"):
        return False

    try:
        # Resolve hostname to IPv4/IPv6 address
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            for blocked_net in BLOCKED_IP_NETWORKS:
                if ip_obj in blocked_net:
                    return False
    except (socket.gaierror, ValueError):
        # Unresolvable hostname
        return False

    return True


def clean_url(url: str) -> str:
    """Canonicalizes and cleans a URL:

    1. Trims leading/trailing whitespace.
    2. Strips URL fragments (#hash).
    3. Normalizes scheme and host to lowercase.
    4. Strips marketing/tracking and session query parameters.
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

    # Filter out tracking and session query parameters
    query = ""
    if parts.query:
        filtered_queries = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if k.lower() not in STRIP_PARAMS
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
    """Generates a safe filesystem filename from a URL path."""
    try:
        parts = urlsplit(url)
        path = parts.path.strip("/")
        if not path:
            return f"index{ext}"

        # Replace path separators and illegal characters with underscores
        slug = re.sub(r'[\/\\:?"*<>|]+', "_", path)
        slug = re.sub(r"_+", "_", slug).strip("_")

        if not slug:
            return f"index{ext}"

        if slug.lower().endswith(ext.lower()):
            return slug

        if len(slug) > 180:
            slug = slug[:180]

        return f"{slug}{ext}"
    except Exception:
        import uuid
        return f"page_{uuid.uuid4().hex[:8]}{ext}"
