"""PDF / document detection without full-body downloads."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

PDF_MAGIC = b"%PDF-"

# Future formats: keep architecture open without expanding scope.
KNOWN_DOC_EXTENSIONS = {
    ".pdf": "pdf",
    ".epub": "epub",
    ".txt": "txt",
    ".doc": "doc",
    ".docx": "docx",
    ".ppt": "ppt",
    ".pptx": "pptx",
    ".zip": "zip",
}


@dataclass
class DetectionResult:
    is_pdf: bool
    confidence: float
    method: str
    mime_type: str | None = None
    filename: str | None = None
    content_length: int | None = None
    format_hint: str = "pdf"


def parse_content_disposition(header: str | None) -> str | None:
    if not header:
        return None
    match = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", header, flags=re.I)
    if match:
        return urllib.parse.unquote(match.group(1).strip().strip("\"'"))
    match = re.search(r'filename\s*=\s*"([^"]+)"', header, flags=re.I)
    if match:
        return match.group(1)
    match = re.search(r"filename\s*=\s*([^;]+)", header, flags=re.I)
    if match:
        return match.group(1).strip().strip("'\"")
    return None


def url_extension(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    return Path(urllib.parse.unquote(path)).suffix.lower()


def detect_from_headers(
    url: str,
    *,
    content_type: str | None = None,
    content_disposition: str | None = None,
    content_length: str | int | None = None,
) -> DetectionResult:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    filename = parse_content_disposition(content_disposition)
    length: int | None = None
    if content_length not in (None, ""):
        try:
            length = int(content_length)
        except (TypeError, ValueError):
            length = None

    ext = url_extension(url)
    fname_ext = Path(filename or "").suffix.lower() if filename else ""

    if mime == "application/pdf":
        return DetectionResult(True, 0.98, "content_type", mime, filename, length, "pdf")
    if (filename or "").lower().endswith(".pdf") or fname_ext == ".pdf":
        return DetectionResult(True, 0.95, "content_disposition", mime or "application/pdf", filename, length, "pdf")
    if ext == ".pdf":
        # URL says pdf but MIME might still be HTML (fake.pdf). Soft confirm until magic/body check.
        if mime.startswith("text/html") or mime in {"application/xhtml+xml", "text/plain"}:
            return DetectionResult(False, 0.2, "url_pdf_but_html_mime", mime, filename, length, "pdf")
        return DetectionResult(True, 0.85, "url_extension", mime or "application/pdf", filename, length, "pdf")

    # Other document types — candidate only for future expansion
    for candidate_ext, hint in KNOWN_DOC_EXTENSIONS.items():
        if hint == "pdf":
            continue
        if ext == candidate_ext or fname_ext == candidate_ext or hint in mime:
            return DetectionResult(False, 0.5, "other_document", mime, filename, length, hint)

    return DetectionResult(False, 0.0, "none", mime or None, filename, length, "unknown")


def detect_from_magic(prefix: bytes, *, url: str = "", content_type: str | None = None) -> DetectionResult:
    if prefix.startswith(PDF_MAGIC):
        return DetectionResult(True, 1.0, "magic_bytes", content_type or "application/pdf", None, None, "pdf")
    # HTML disguised as .pdf
    head = prefix[:200].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:64]:
        return DetectionResult(False, 0.0, "html_body", content_type, None, None, "html")
    base = detect_from_headers(url, content_type=content_type)
    return base


def is_likely_pdf_candidate_url(url: str, anchor_text: str = "") -> bool:
    blob = f"{url} {anchor_text}".lower()
    if url_extension(url) == ".pdf":
        return True
    return any(term in blob for term in ("download", "pdf", "ebook", "full text", "view book", "get book"))
