from __future__ import annotations

import html
import mimetypes
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

USER_AGENT = "HADES-DeepWebDownloader/1.0 (+authorized archival/research use)"
HTML_MAX_BYTES = 12 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024

DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".csv",
    ".xls", ".xlsx", ".xlsm", ".ods", ".ppt", ".pptx", ".odp",
    ".epub", ".mobi", ".azw", ".azw3", ".djvu", ".ps",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
    ".json", ".xml", ".yaml", ".yml", ".tex",
}
DOWNLOAD_MIME_PREFIXES = (
    "application/pdf", "application/zip", "application/x-7z-compressed",
    "application/x-rar-compressed", "application/vnd.", "application/msword",
    "application/rtf", "application/epub+zip", "application/octet-stream",
    "text/plain", "text/csv",
)
LINK_ATTRS = {
    "href", "src", "data-href", "data-url", "data-src", "data-download",
    "data-file", "action", "poster",
}


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", ""}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def sanitize_filename(name: str, fallback: str = "download") -> str:
    name = html.unescape(name or "").strip().replace("\x00", "")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or fallback)[:180]


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http:// and https:// URLs are supported.")
    return urllib.parse.urlunsplit((
        parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""
    ))


def _is_private_ip_literal(host: str) -> bool:
    import ipaddress

    host = (host or "").lower().strip("[]")
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal"}:
        return True
    if host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def is_blocked_ssrf_host(host: str) -> bool:
    """Block private/loopback/link-local/metadata-style hosts (no DNS rebinding resolve here)."""
    return _is_private_ip_literal(host)


def assert_public_crawl_url(url: str) -> str:
    normalized = normalize_url(url)
    host = urllib.parse.urlsplit(normalized).hostname or ""
    if is_blocked_ssrf_host(host):
        raise ValueError(f"Private/local host blocked: {host}")
    return normalized


def same_site(host: str, seed_host: str) -> bool:
    host = (host or "").lower().split(":", 1)[0].strip(".")
    seed_host = (seed_host or "").lower().split(":", 1)[0].strip(".")
    return host == seed_host or host.endswith("." + seed_host) or seed_host.endswith("." + host)


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.meta_refresh: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = {k.lower(): v for k, v in attrs if k}
        for key in LINK_ATTRS:
            value = amap.get(key)
            if value:
                self.links.append(value.strip())
        if tag.lower() == "meta" and (amap.get("http-equiv") or "").lower() == "refresh":
            match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", amap.get("content") or "", flags=re.I)
            if match:
                self.meta_refresh.append(match.group(1).strip())


def extract_links(html_text: str, base_url: str) -> list[str]:
    parser = LinkExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    candidates = list(parser.links) + list(parser.meta_refresh)
    candidates.extend(re.findall(r"https?://[^\s\"'<>\\)]+", html_text, flags=re.I))

    result: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        raw = html.unescape(raw).strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        try:
            normalized = normalize_url(urllib.parse.urljoin(base_url, raw))
        except Exception:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def filename_from_headers(url: str, headers) -> str:
    disposition = headers.get("Content-Disposition", "") if headers else ""
    if disposition:
        match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.I)
        if match:
            return sanitize_filename(urllib.parse.unquote(match.group(1)))
        match = re.search(r'filename\s*=\s*"([^"]+)"', disposition, flags=re.I)
        if match:
            return sanitize_filename(match.group(1))
        match = re.search(r"filename\s*=\s*([^;]+)", disposition, flags=re.I)
        if match:
            return sanitize_filename(match.group(1).strip("'\" "))
    base = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    return sanitize_filename(base) if base else "download"


def extension_from_content_type(content_type: str) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    explicit = {
        "application/pdf": ".pdf", "application/epub+zip": ".epub",
        "application/rtf": ".rtf", "text/plain": ".txt", "text/csv": ".csv",
        "application/json": ".json", "application/xml": ".xml", "text/xml": ".xml",
    }
    if mime in explicit:
        return explicit[mime]
    guessed = mimetypes.guess_extension(mime) or ""
    return guessed if guessed and len(guessed) <= 8 else ""


def is_probable_download(url: str, content_type: str, disposition: str) -> bool:
    ext = Path(urllib.parse.urlsplit(url).path.lower()).suffix.lower()
    if ext in DOCUMENT_EXTENSIONS or "attachment" in (disposition or "").lower():
        return True
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime.startswith("text/html") or mime == "application/xhtml+xml":
        return False
    return any(mime.startswith(prefix) for prefix in DOWNLOAD_MIME_PREFIXES)
