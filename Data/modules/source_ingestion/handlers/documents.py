"""Document handlers — PDF / HTML / markdown / rst via consolidated extraction."""

from __future__ import annotations

import codecs
import hashlib
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.hashing import sha256_text

from ..settings import SourceIngestionSettings
from ..types import (
    ContentRef,
    DetectionResult,
    ERROR_OCR_REQUIRED,
    MemberOutcome,
    NormalizedArtifact,
    PARSER_VERSION,
    SourceKind,
)
from .base import HandlerCapabilities

# Small-file convenience path may materialize decoded text in memory.
# Above this threshold, prefer file-backed normalized artifacts / iterators.
INLINE_TEXT_BYTES = 2 * 1024 * 1024


def _hash_file(path: Path, *, max_bytes: int | None = None) -> tuple[str, int]:
    hasher = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                break
            hasher.update(chunk)
    return hasher.hexdigest(), total


def _normalized_out_path(path: Path, *, staging_root: Path | None) -> Path:
    if staging_root is not None:
        root = ensure_dir(Path(staging_root) / "_normalized")
    else:
        root = ensure_dir(path.parent / ".source_ingestion_normalized")
    digest_prefix = _hash_file(path, max_bytes=1024 * 1024)[0][:16]
    return root / f"{path.stem}.{digest_prefix}.normalized.txt"


class DocumentHandler:
    capabilities = HandlerCapabilities(
        handler_id="document",
        kinds=frozenset({SourceKind.DOCUMENT}),
        extensions=frozenset(
            {".pdf", ".md", ".markdown", ".rst", ".html", ".htm", ".xhtml", ".txt", ".log"}
        ),
        supports_stream=False,
        requires_path=True,
    )

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool:
        if detection.kind == SourceKind.DOCUMENT:
            return True
        ext = detection.extension.lower()
        return ext in self.capabilities.extensions and detection.kind in {
            SourceKind.DOCUMENT,
            SourceKind.PLAIN_TEXT,
        }

    def inspect(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        settings: SourceIngestionSettings,
    ) -> dict[str, Any]:
        return {"handler": "document", "path": str(path), "kind": detection.kind.value}

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        ext = detection.extension.lower() or Path(relative_path).suffix.lower()
        if ext == ".pdf":
            return self._ingest_pdf(
                path,
                detection=detection,
                relative_path=relative_path,
                staging_root=staging_root,
            )
        if ext in {".html", ".htm", ".xhtml"}:
            return self._ingest_via_extraction(
                path,
                detection=detection,
                relative_path=relative_path,
                staging_root=staging_root,
            )
        return self._ingest_text(
            path,
            detection=detection,
            relative_path=relative_path,
            parser="plain_text",
            staging_root=staging_root,
        )

    def _ingest_pdf(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        size = path.stat().st_size if path.is_file() else 0
        # Large PDFs: stream pages via path-backed iterator — never mandatory read_bytes.
        if size > INLINE_TEXT_BYTES:
            return self._ingest_pdf_streaming(
                path,
                detection=detection,
                relative_path=relative_path,
                staging_root=staging_root,
            )

        from Data.modules.documents.extraction import extract_document

        try:
            extraction = extract_document(path, max_pages=200)
        except Exception as exc:  # noqa: BLE001
            return NormalizedArtifact(
                source_kind=SourceKind.DOCUMENT,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type="application/pdf",
                parser="pdf",
                parser_version=PARSER_VERSION,
                content_hash=_hash_file(path)[0],
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code="SOURCE_PARSE_FAILED",
                skip_reason=str(exc)[:200],
                retryable=True,
                provenance={"relative_path": relative_path},
            )

        if "ocr_scan" in (extraction.unsupported or []) or not extraction.pages:
            texts = [
                str(p.get("text") or "") if isinstance(p, dict) else str(getattr(p, "text", "") or "")
                for p in (extraction.pages or [])
            ]
            joined = "\n\n".join(t for t in texts if t.strip()).strip()
            if not joined:
                return self._ingest_pdf_legacy(path, detection=detection, relative_path=relative_path)

        pages_out: list[dict[str, Any]] = []
        parts: list[str] = []
        for index, page in enumerate(extraction.pages or []):
            if isinstance(page, dict):
                text = str(page.get("text") or "")
                num = int(page.get("page_number") or page.get("index", index) + 1)
            else:
                text = str(getattr(page, "text", "") or "")
                num = index + 1
            pages_out.append({"page_number": num, "chars": len(text)})
            if text.strip():
                parts.append(f"[page {num}]\n{text}".strip())
        joined = "\n\n".join(parts).strip()
        if not joined:
            return NormalizedArtifact(
                source_kind=SourceKind.DOCUMENT,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type="application/pdf",
                parser=str(extraction.backend or "pdf"),
                parser_version=PARSER_VERSION,
                content_hash=extraction.content_sha256 or _hash_file(path)[0],
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code=ERROR_OCR_REQUIRED,
                skip_reason="PDF has no extractable text; OCR/document_ai required",
                unsupported_features=list(extraction.unsupported or ["ocr"]),
                provenance={
                    "relative_path": relative_path,
                    "page_count": len(pages_out),
                    "pdf_class": "scanned_or_image_only",
                    "text_extraction": "empty",
                    "ocr_status": "required",
                    "legacy_error_code": "PDF_NO_EXTRACTABLE_TEXT",
                },
                retryable=False,
            )
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="application/pdf",
            parser=str(extraction.backend or "pdf"),
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(joined),
            content=ContentRef(text=joined),
            structured_metadata={"pages": pages_out, "page_count": len(pages_out)},
            provenance={
                "relative_path": relative_path,
                "page_count": len(pages_out),
                "pages": pages_out,
                "pages_parsed": len(pages_out),
                "pages_total": len(pages_out),
            },
            unsupported_features=list(extraction.unsupported or []),
            outcome=MemberOutcome.SUCCESS,
        )

    def _ingest_pdf_streaming(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        staging_root: Path | None = None,
        max_pages: int = 200,
    ) -> NormalizedArtifact:
        """Path-backed page iterator for large PDFs — no full-file read_bytes."""
        out_path = _normalized_out_path(path, staging_root=staging_root)
        pages_out: list[dict[str, Any]] = []
        hasher = hashlib.sha256()
        wrote_any = False

        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError:
            PdfReader = None  # type: ignore[assignment,misc]

        if PdfReader is not None:
            try:
                # PdfReader accepts a path/stream handle — does not require read_bytes().
                reader = PdfReader(str(path))
                with open(out_path, "w", encoding="utf-8") as handle:
                    for index, page in enumerate(reader.pages):
                        if index >= max_pages:
                            break
                        text = page.extract_text() or ""
                        num = index + 1
                        pages_out.append({"page_number": num, "chars": len(text)})
                        if text.strip():
                            block = f"[page {num}]\n{text}".strip() + "\n\n"
                            handle.write(block)
                            hasher.update(block.encode("utf-8"))
                            wrote_any = True
            except Exception as exc:  # noqa: BLE001
                return NormalizedArtifact(
                    source_kind=SourceKind.DOCUMENT,
                    title=Path(relative_path).name,
                    relative_path=relative_path,
                    mime_type="application/pdf",
                    parser="pdf_stream",
                    parser_version=PARSER_VERSION,
                    content_hash=_hash_file(path)[0],
                    content=ContentRef(text=""),
                    outcome=MemberOutcome.FAILED,
                    error_code="SOURCE_PARSE_FAILED",
                    skip_reason=str(exc)[:200],
                    retryable=True,
                    provenance={
                        "relative_path": relative_path,
                        "streaming": True,
                        "inline_threshold_bytes": INLINE_TEXT_BYTES,
                    },
                )
        else:
            # No pypdf: stream-hash the raw file for identity; text requires OCR/document_ai.
            return NormalizedArtifact(
                source_kind=SourceKind.DOCUMENT,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type="application/pdf",
                parser="pdf_stream",
                parser_version=PARSER_VERSION,
                content_hash=_hash_file(path)[0],
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code=ERROR_OCR_REQUIRED,
                skip_reason="Large PDF without pypdf; OCR/document_ai required (no full read_bytes)",
                unsupported_features=["ocr", "pypdf"],
                provenance={
                    "relative_path": relative_path,
                    "streaming": True,
                    "pdf_class": "large_no_pypdf",
                    "ocr_status": "required",
                    "pages_parsed": "UNMEASURED",
                    "pages_total": "UNMEASURED",
                },
                retryable=False,
            )

        if not wrote_any:
            return NormalizedArtifact(
                source_kind=SourceKind.DOCUMENT,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type="application/pdf",
                parser="pdf_stream",
                parser_version=PARSER_VERSION,
                content_hash=_hash_file(path)[0],
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code=ERROR_OCR_REQUIRED,
                skip_reason="PDF has no extractable text; OCR/document_ai required",
                unsupported_features=["ocr"],
                provenance={
                    "relative_path": relative_path,
                    "page_count": len(pages_out),
                    "pages_parsed": len(pages_out),
                    "pages_total": len(pages_out),
                    "pdf_class": "scanned_or_image_only",
                    "text_extraction": "empty",
                    "ocr_status": "required",
                    "streaming": True,
                    "legacy_error_code": "PDF_NO_EXTRACTABLE_TEXT",
                },
                retryable=False,
            )

        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="application/pdf",
            parser="pdf_stream",
            parser_version=PARSER_VERSION,
            content_hash=hasher.hexdigest(),
            content=ContentRef(path=str(out_path)),
            structured_metadata={"pages": pages_out, "page_count": len(pages_out)},
            provenance={
                "relative_path": relative_path,
                "page_count": len(pages_out),
                "pages": pages_out,
                "pages_parsed": len(pages_out),
                "pages_total": len(pages_out),
                "streaming": True,
                "normalized_path": str(out_path),
            },
            outcome=MemberOutcome.SUCCESS,
        )

    def _ingest_pdf_legacy(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
    ) -> NormalizedArtifact:
        # Legacy small-file path only — never mandatory for large PDFs.
        size = path.stat().st_size if path.is_file() else 0
        if size > INLINE_TEXT_BYTES:
            return NormalizedArtifact(
                source_kind=SourceKind.DOCUMENT,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type="application/pdf",
                parser="pdf",
                parser_version=PARSER_VERSION,
                content_hash=_hash_file(path)[0],
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code=ERROR_OCR_REQUIRED,
                skip_reason="Large PDF legacy read_bytes path refused; use streaming/OCR",
                unsupported_features=["ocr"],
                provenance={
                    "relative_path": relative_path,
                    "legacy_read_bytes_refused": True,
                    "size_bytes": size,
                    "inline_threshold_bytes": INLINE_TEXT_BYTES,
                },
                retryable=False,
            )
        raw = path.read_bytes()
        from Data.modules.research.uploads import _parse_pdf

        try:
            parsed = _parse_pdf(raw, filename=Path(relative_path).name, max_pages=200)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "SOURCE_PARSE_FAILED")
            return NormalizedArtifact(
                source_kind=SourceKind.DOCUMENT,
                title=Path(relative_path).name,
                relative_path=relative_path,
                mime_type="application/pdf",
                parser="pdf",
                parser_version=PARSER_VERSION,
                content_hash=hashlib.sha256(raw).hexdigest(),
                content=ContentRef(text=""),
                outcome=MemberOutcome.FAILED,
                error_code=str(code),
                skip_reason=str(getattr(exc, "message", exc))[:200],
                retryable=True,
            )
        text = str(parsed.get("text") or "")
        page_count = parsed.get("page_count")
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="application/pdf",
            parser=str(parsed.get("parser") or "pdf"),
            parser_version=str(parsed.get("parser_version") or PARSER_VERSION),
            content_hash=sha256_text(text),
            content=ContentRef(text=text),
            structured_metadata={"structure": parsed.get("structure"), "page_count": page_count},
            provenance={
                "relative_path": relative_path,
                "page_count": page_count,
                "pages_parsed": page_count,
                "pages_total": page_count,
                "pages": [
                    {"page_number": p.get("page_number"), "chars": len(p.get("text") or "")}
                    for p in (parsed.get("pages") or [])
                ],
            },
            outcome=MemberOutcome.SUCCESS,
        )

    def _ingest_via_extraction(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        size = path.stat().st_size if path.is_file() else 0
        if size > INLINE_TEXT_BYTES:
            return self._ingest_html_streaming(
                path,
                detection=detection,
                relative_path=relative_path,
                staging_root=staging_root,
            )

        from Data.modules.documents.extraction import extract_document

        extraction = extract_document(path)
        parts: list[str] = []
        for page in extraction.pages or []:
            if isinstance(page, dict):
                parts.append(str(page.get("text") or ""))
            else:
                parts.append(str(getattr(page, "text", "") or ""))
        text = "\n\n".join(p for p in parts if p.strip()).strip()
        if not text:
            # Small-file convenience fallback only.
            text = path.read_text(encoding="utf-8", errors="replace")
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "text/html",
            parser=str(extraction.backend or "html"),
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(text),
            content=ContentRef(text=text),
            structured_metadata={
                "tables": len(extraction.tables or []),
                "values": len(extraction.values or []),
            },
            provenance={"relative_path": relative_path},
            outcome=MemberOutcome.SUCCESS,
        )

    def _ingest_html_streaming(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        """Stream-decode large HTML into a file-backed normalized text artifact."""
        out_path = _normalized_out_path(path, staging_root=staging_root)
        hasher = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        ensure_dir(out_path.parent)
        with open(path, "rb") as src, open(out_path, "w", encoding="utf-8") as dst:
            buf: list[str] = []
            in_tag = False

            def _flush(force: bool = False) -> None:
                if force or len(buf) >= 4096:
                    block = "".join(buf)
                    buf.clear()
                    if block:
                        dst.write(block)
                        hasher.update(block.encode("utf-8"))

            while True:
                chunk = src.read(1024 * 64)
                if not chunk:
                    break
                for ch in decoder.decode(chunk):
                    if ch == "<":
                        in_tag = True
                        continue
                    if ch == ">":
                        in_tag = False
                        continue
                    if not in_tag:
                        buf.append(ch)
                        _flush()
            for ch in decoder.decode(b"", final=True):
                if ch == "<":
                    in_tag = True
                    continue
                if ch == ">":
                    in_tag = False
                    continue
                if not in_tag:
                    buf.append(ch)
            _flush(force=True)
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "text/html",
            parser="html_stream",
            parser_version=PARSER_VERSION,
            content_hash=hasher.hexdigest(),
            content=ContentRef(path=str(out_path)),
            structured_metadata={"streaming": True},
            provenance={
                "relative_path": relative_path,
                "streaming": True,
                "normalized_path": str(out_path),
                "pages_parsed": "UNMEASURED",
                "pages_total": "UNMEASURED",
            },
            outcome=MemberOutcome.SUCCESS,
        )

    def _ingest_text(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        parser: str,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact:
        ref, digest = materialize_text_content(path, staging_root=staging_root)
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT if detection.kind == SourceKind.DOCUMENT else SourceKind.PLAIN_TEXT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "text/plain",
            parser=parser,
            parser_version=PARSER_VERSION,
            content_hash=digest,
            content=ref,
            provenance={
                "relative_path": relative_path,
                "streaming": ref.path is not None,
                "inline_chars": len(ref.text) if ref.text is not None else None,
            },
            outcome=MemberOutcome.SUCCESS,
        )


def materialize_text_content(
    path: Path,
    *,
    staging_root: Path | None = None,
    inline_threshold: int = INLINE_TEXT_BYTES,
    chunk_size: int = 1024 * 256,
) -> tuple[ContentRef, str]:
    """Decode text without mandatory full bytearray materialization.

    Small files may return an in-memory ContentRef. Large files stream into a
    file-backed normalized artifact and return ContentRef(path=...).
    """
    size = path.stat().st_size if path.is_file() else 0
    if size <= inline_threshold:
        text = _decode_file_to_str(path, chunk_size=chunk_size)
        return ContentRef(text=text), sha256_text(text)

    out_path = _normalized_out_path(path, staging_root=staging_root)
    digest = _stream_decode_to_file(path, out_path, chunk_size=chunk_size)
    return ContentRef(path=str(out_path)), digest


def _decode_file_to_str(path: Path, *, chunk_size: int = 1024 * 256) -> str:
    """Incremental decode for small files — no full bytearray buffer of raw bytes."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            decoder = codecs.getincrementaldecoder(encoding)("strict")
            parts: list[str] = []
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    parts.append(decoder.decode(chunk))
                parts.append(decoder.decode(b"", final=True))
            return "".join(parts)
        except UnicodeDecodeError:
            continue
    # Last resort: replace errors
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    parts = []
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            parts.append(decoder.decode(chunk))
        parts.append(decoder.decode(b"", final=True))
    return "".join(parts)


def _stream_decode_to_file(
    path: Path,
    out_path: Path,
    *,
    chunk_size: int = 1024 * 256,
) -> str:
    """Stream-decode ``path`` into ``out_path``; return SHA-256 of UTF-8 text bytes."""
    ensure_dir(out_path.parent)
    hasher = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    with open(path, "rb") as src, open(out_path, "w", encoding="utf-8") as dst:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                dst.write(text)
                hasher.update(text.encode("utf-8"))
        text = decoder.decode(b"", final=True)
        if text:
            dst.write(text)
            hasher.update(text.encode("utf-8"))
    return hasher.hexdigest()


def _read_text_streaming(
    path: Path,
    *,
    chunk_size: int = 1024 * 256,
    staging_root: Path | None = None,
    inline_threshold: int = INLINE_TEXT_BYTES,
) -> str:
    """Compatibility wrapper — prefers streaming materialization.

    Large files are decoded to a file-backed artifact first; the returned string
    is only loaded when a caller still requires a str. Prefer
    :func:`materialize_text_content` for new code paths.
    """
    ref, _digest = materialize_text_content(
        path,
        staging_root=staging_root,
        inline_threshold=inline_threshold,
        chunk_size=chunk_size,
    )
    return ref.read_text()


def iter_text_chunks(
    path: Path,
    *,
    chunk_size: int = 1024 * 256,
) -> Iterator[str]:
    """Yield decoded text chunks without assembling the full document."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                yield text
        text = decoder.decode(b"", final=True)
        if text:
            yield text
