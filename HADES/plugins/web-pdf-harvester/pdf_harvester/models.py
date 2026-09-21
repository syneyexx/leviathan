"""Structured models for crawl nodes, resources, sessions and errors."""

from __future__ import annotations

import enum
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"crawl_{stamp}_{uuid.uuid4().hex[:10]}"


def new_resource_id(normalized_url: str) -> str:
    """Stable id derived from normalized URL (not random)."""
    digest = uuid.uuid5(uuid.NAMESPACE_URL, normalized_url)
    return f"res_{digest.hex[:16]}"


class NodeState(str, enum.Enum):
    QUEUED = "QUEUED"
    VISITING = "VISITING"
    VISITED = "VISITED"
    REDIRECTED = "REDIRECTED"
    RESOURCE_CANDIDATE = "RESOURCE_CANDIDATE"
    PDF_CONFIRMED = "PDF_CONFIRMED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ResourceStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    BLOCKED = "blocked"
    FAILED = "failed"


class DownloadStatus(str, enum.Enum):
    NOT_DOWNLOADED = "not_downloaded"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class ErrorClass(str, enum.Enum):
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    ROBOTS_BLOCKED = "ROBOTS_BLOCKED"
    CAPTCHA_BLOCKED = "CAPTCHA_BLOCKED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PAYWALL_BLOCKED = "PAYWALL_BLOCKED"
    BROWSER_ERROR = "BROWSER_ERROR"
    INVALID_URL = "INVALID_URL"
    TOO_DEEP = "TOO_DEEP"
    CRAWL_BUDGET_EXCEEDED = "CRAWL_BUDGET_EXCEEDED"
    PDF_VALIDATION_FAILED = "PDF_VALIDATION_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    FILESYSTEM_ERROR = "FILESYSTEM_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CrawlNode:
    url: str
    normalized_url: str
    parent_url: str | None = None
    referrer: str | None = None
    depth: int = 0
    external_hops: int = 0
    hostname: str = ""
    page_title: str | None = None
    anchor_text: str | None = None
    discovery_method: str = "seed"
    click_path: list[str] = field(default_factory=list)
    redirect_chain: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    state: str = NodeState.QUEUED.value
    created_at: str = field(default_factory=utc_now_iso)
    error: str | None = None
    error_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrawlNode:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ResourceRecord:
    id: str
    title: str | None = None
    author: str | None = None
    description: str | None = None
    category: str | None = None
    page_count: int | None = None
    source_site: str | None = None
    source_page: str | None = None
    discovered_url: str = ""
    final_url: str | None = None
    normalized_url: str = ""
    canonical_url: str | None = None
    hostname: str = ""
    mime_type: str | None = None
    filename: str | None = None
    content_length: int | None = None
    status: str = ResourceStatus.CANDIDATE.value
    download_status: str = DownloadStatus.NOT_DOWNLOADED.value
    discovered_at: str = field(default_factory=utc_now_iso)
    verified_at: str | None = None
    depth: int = 0
    anchor_text: str | None = None
    discovery_method: str = "http"
    click_path: list[str] = field(default_factory=list)
    redirect_chain: list[str] = field(default_factory=list)
    sha256: str | None = None
    local_path: str | None = None
    error: str | None = None
    error_class: str | None = None
    session_id: str | None = None
    format_hint: str = "pdf"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class CrawlConfig:
    start_urls: list[str] = field(default_factory=list)
    max_depth: int = 6
    max_pages: int = 5000
    max_urls_per_page: int = 200
    max_external_hops: int = 3
    max_concurrent_requests: int = 8
    max_browser_pages: int = 2
    request_timeout_seconds: float = 30.0
    browser_timeout_seconds: float = 45.0
    rate_limit_ms: int = 750
    max_retries: int = 3
    max_redirects: int = 10
    respect_robots_txt: bool = True
    same_domain_first: bool = True
    allow_external_resource_hosts: bool = True
    verify_pdf_headers: bool = True
    download_concurrency: int = 3
    chunk_size: int = 256 * 1024
    resume: bool = False
    allow_private_hosts: bool = False
    data_dir: str = "data/pdf_harvester"
    use_browser: bool = True
    min_enqueue_score: float = -5.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CrawlConfig:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        cleaned = {k: v for k, v in data.items() if k in known}
        return cls(**cleaned)


@dataclass
class CrawlStats:
    session_id: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    pages_visited: int = 0
    pages_queued: int = 0
    pdfs_confirmed: int = 0
    pdf_candidates: int = 0
    duplicate_urls: int = 0
    redirects: int = 0
    blocked_pages: int = 0
    errors: int = 0
    browser_fallbacks: int = 0
    external_hosts_followed: int = 0
    current_host: str | None = None
    cancelled: bool = False
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
