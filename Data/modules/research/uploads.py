"""Research source file upload, parsing, and LOCAL_FILE ingestion."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_text

from .store import ResearchStore, utc_now
from .types import BrainStatus, ParseStatus, ResearchError, ResearchSource, SourceType

# Soft ceiling — operators can tune via ResearchService.max_upload_bytes.
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024

SUPPORTED_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".md", ".markdown", ".csv", ".json", ".log", ".rst"}
)

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".log": "text/plain",
    ".rst": "text/x-rst",
}


def sanitize_filename(name: str) -> str:
    base = Path(name or "upload.bin").name
    base = base.replace("\x00", "")
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base, flags=re.UNICODE)
    base = base.strip(" .") or "upload.bin"
    if base in {".", ".."}:
        base = "upload.bin"
    return base[:180]


def stream_hash_and_write(
    stream: BinaryIO,
    dest: Path,
    *,
    max_bytes: int,
) -> tuple[str, int]:
    """Stream to a temp file, hash, then atomically publish. Rejects oversized uploads."""
    ensure_dir(dest.parent)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    hasher = hashlib.sha256()
    total = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = stream.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ResearchError(
                        "SOURCE_TOO_LARGE",
                        f"Upload exceeds maximum size of {max_bytes} bytes",
                        http_status=413,
                        details={"max_bytes": max_bytes, "received": total},
                    )
                hasher.update(chunk)
                out.write(chunk)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return hasher.hexdigest(), total


def parse_bytes(
    raw: bytes,
    *,
    filename: str,
    max_pages: int = 200,
) -> dict[str, Any]:
    """Parse uploaded bytes into extractable text + provenance. Never fabricates content."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ResearchError(
            "UNSUPPORTED_SOURCE_TYPE",
            f"Unsupported file type: {ext or '(none)'}",
            http_status=422,
            details={"filename": filename, "supported": sorted(SUPPORTED_EXTENSIONS)},
        )

    if ext == ".pdf":
        return _parse_pdf(raw, filename=filename, max_pages=max_pages)
    if ext == ".json":
        return _parse_json(raw, filename=filename)
    if ext == ".csv":
        return _parse_csv(raw, filename=filename)
    # txt / md / markdown / log / rst
    text = _decode_text(raw)
    return {
        "text": text,
        "parser": "plain_text",
        "parser_version": "1",
        "page_count": None,
        "pages": [],
        "mime_type": MIME_BY_EXT.get(ext, "text/plain"),
        "structure": None,
    }


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_json(raw: bytes, *, filename: str) -> dict[str, Any]:
    try:
        data = json.loads(_decode_text(raw))
    except json.JSONDecodeError as exc:
        raise ResearchError(
            "SOURCE_PARSE_FAILED",
            f"Malformed JSON: {exc}",
            http_status=422,
            details={"filename": filename},
        ) from exc
    # Preserve structure rather than concatenating random values.
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    return {
        "text": text,
        "parser": "json",
        "parser_version": "1",
        "page_count": None,
        "pages": [],
        "mime_type": "application/json",
        "structure": data if isinstance(data, (dict, list)) else {"value": data},
    }


def _parse_csv(raw: bytes, *, filename: str) -> dict[str, Any]:
    text = _decode_text(raw)
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    try:
        for row in reader:
            rows.append([str(c) for c in row])
    except csv.Error as exc:
        raise ResearchError(
            "SOURCE_PARSE_FAILED",
            f"Malformed CSV: {exc}",
            http_status=422,
            details={"filename": filename},
        ) from exc
    if not rows:
        raise ResearchError(
            "SOURCE_PARSE_FAILED",
            "CSV contained no rows",
            http_status=422,
            details={"filename": filename},
        )
    header = rows[0]
    lines = [", ".join(header)]
    for row in rows[1:]:
        pairs = []
        for i, cell in enumerate(row):
            key = header[i] if i < len(header) else f"col_{i}"
            pairs.append(f"{key}={cell}")
        lines.append("; ".join(pairs))
    return {
        "text": "\n".join(lines),
        "parser": "csv",
        "parser_version": "1",
        "page_count": None,
        "pages": [],
        "mime_type": "text/csv",
        "structure": {"headers": header, "row_count": max(0, len(rows) - 1)},
    }


def _parse_pdf(raw: bytes, *, filename: str, max_pages: int) -> dict[str, Any]:
    if not raw.startswith(b"%PDF"):
        raise ResearchError(
            "SOURCE_PARSE_FAILED",
            "File does not look like a PDF",
            http_status=422,
            details={"filename": filename},
        )
    pages: list[dict[str, Any]] = []
    backend = "pypdf"
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(io.BytesIO(raw))
        for index, page in enumerate(reader.pages):
            if index >= max_pages:
                break
            text = page.extract_text() or ""
            pages.append({"page_number": index + 1, "text": text, "kind": "pdf"})
    except ImportError:
        backend = "pdf_stream_fallback"
        # Minimal stream fallback (no OCR) — same honesty as documents.extraction.
        decoded = raw.decode("latin-1", errors="ignore")
        page_chunks = re.split(r"/Type\s*/Page\b", decoded)[1:] or [decoded]
        for index, chunk in enumerate(page_chunks[:max_pages]):
            literals = re.findall(r"\((?:\\.|[^\\)])*\)", chunk)
            joined = " ".join(lit[1:-1].replace("\\n", "\n") for lit in literals)
            pages.append({"page_number": index + 1, "text": joined, "kind": "pdf_stream"})
    except Exception as exc:  # noqa: BLE001
        raise ResearchError(
            "SOURCE_PARSE_FAILED",
            f"PDF parse failed: {exc}",
            http_status=422,
            details={"filename": filename},
        ) from exc

    joined_text = "\n\n".join(
        f"[page {p['page_number']}]\n{p['text']}".strip() for p in pages if (p.get("text") or "").strip()
    ).strip()
    if not joined_text:
        raise ResearchError(
            "PDF_NO_EXTRACTABLE_TEXT",
            "PDF has no extractable text (OCR would be required for scanned/image-only PDFs)",
            http_status=422,
            details={"filename": filename, "page_count": len(pages), "parser": backend},
        )
    return {
        "text": joined_text,
        "parser": backend,
        "parser_version": "1",
        "page_count": len(pages),
        "pages": pages,
        "mime_type": "application/pdf",
        "structure": {"pages": [{"page_number": p["page_number"], "chars": len(p.get("text") or "")} for p in pages]},
    }


class UploadIngestor:
    """Durable LOCAL_FILE ingestion under the research corpus layout."""

    def __init__(
        self,
        store: ResearchStore,
        *,
        sources_root: Path,
        snapshots_root: Path,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    ) -> None:
        self.store = store
        self.sources_root = ensure_dir(Path(sources_root))
        self.snapshots_root = ensure_dir(Path(snapshots_root))
        self.max_upload_bytes = int(max_upload_bytes)

    def from_upload_stream(
        self,
        project_id: str,
        *,
        filename: str,
        stream: BinaryIO,
        content_type: str | None = None,
    ) -> tuple[ResearchSource, str]:
        safe_name = sanitize_filename(filename)
        ext = Path(safe_name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ResearchError(
                "UNSUPPORTED_SOURCE_TYPE",
                f"Unsupported file type: {ext or '(none)'}",
                http_status=422,
                details={"filename": safe_name, "supported": sorted(SUPPORTED_EXTENSIONS)},
            )

        # Path-traversal impossible: only basename, under project dir.
        source_id = str(uuid.uuid4())
        dest_dir = ensure_dir(self.sources_root / project_id)
        raw_path = dest_dir / f"{source_id}__{safe_name}"
        if ".." in raw_path.parts or not str(raw_path.resolve()).startswith(str(dest_dir.resolve())):
            raise ResearchError(
                "SOURCE_PATH_INVALID",
                "Refusing unsafe upload path",
                http_status=400,
            )

        content_hash, size = stream_hash_and_write(
            stream, raw_path, max_bytes=self.max_upload_bytes
        )
        raw = raw_path.read_bytes()
        try:
            parsed = parse_bytes(raw, filename=safe_name)
        except ResearchError as exc:
            # Persist failed source for honesty / retry visibility.
            failed = ResearchSource(
                source_id=source_id,
                project_id=project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri=f"upload://{safe_name}",
                canonical_uri=f"upload://{project_id}/{content_hash}",
                title=safe_name,
                fetched_at=utc_now(),
                content_hash=content_hash,
                mime_type=content_type or MIME_BY_EXT.get(ext),
                snapshot_path=None,
                parse_status=ParseStatus.FAILED,
                parser=None,
                brain_status=BrainStatus.SKIPPED,
                brain_error=None,
                provenance={
                    "filename": safe_name,
                    "size_bytes": size,
                    "raw_path": str(raw_path),
                    "error_code": exc.code,
                },
                metadata={"error": exc.message},
                created_at=utc_now(),
            )
            self.store.upsert_source(failed)
            raise

        text = parsed["text"]
        text_hash = sha256_text(text)
        snap_dir = ensure_dir(self.snapshots_root / project_id)
        snapshot = snap_dir / f"{source_id}.txt"
        atomic_write_text(snapshot, text)

        source = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.LOCAL_FILE,
            original_uri=f"upload://{safe_name}",
            canonical_uri=f"upload://{project_id}/{content_hash}",
            title=safe_name,
            fetched_at=utc_now(),
            content_hash=content_hash,
            mime_type=parsed.get("mime_type") or content_type or MIME_BY_EXT.get(ext),
            snapshot_path=str(snapshot),
            parse_status=ParseStatus.OK,
            parser=str(parsed.get("parser") or "upload"),
            brain_status=BrainStatus.PENDING,
            provenance={
                "filename": safe_name,
                "size_bytes": size,
                "raw_path": str(raw_path),
                "content_hash": content_hash,
                "text_hash": text_hash,
                "parser": parsed.get("parser"),
                "parser_version": parsed.get("parser_version"),
                "page_count": parsed.get("page_count"),
                "pages": [
                    {"page_number": p.get("page_number"), "chars": len(p.get("text") or "")}
                    for p in (parsed.get("pages") or [])
                ],
                "project_id": project_id,
                "research_source_id": source_id,
            },
            metadata={
                "structure": parsed.get("structure"),
                "upload": True,
            },
            created_at=utc_now(),
        )
        stored = self.store.upsert_source(source)
        if stored.source_id != source.source_id and stored.snapshot_path:
            try:
                text = Path(stored.snapshot_path).read_text(encoding="utf-8")
            except OSError:
                pass
        return stored, text
