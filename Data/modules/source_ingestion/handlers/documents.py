"""Document handlers — PDF / HTML / markdown / rst via consolidated extraction."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_text

from ..settings import SourceIngestionSettings
from ..types import (
    ContentRef,
    DetectionResult,
    MemberOutcome,
    NormalizedArtifact,
    PARSER_VERSION,
    SourceKind,
)
from .base import HandlerCapabilities


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
            return self._ingest_pdf(path, detection=detection, relative_path=relative_path)
        # Prefer documents.extraction for HTML; plain decode for md/rst/txt/log
        if ext in {".html", ".htm", ".xhtml"}:
            return self._ingest_via_extraction(path, detection=detection, relative_path=relative_path)
        return self._ingest_text(path, detection=detection, relative_path=relative_path, parser="plain_text")

    def _ingest_pdf(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
    ) -> NormalizedArtifact:
        # Reuse research-compatible PDF parsing without loading via read_bytes of archives —
        # for PDF we need the file; use path-based open.
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
            # Check for empty text
            texts = [str(p.get("text") or "") if isinstance(p, dict) else str(getattr(p, "text", "") or "") for p in (extraction.pages or [])]
            joined = "\n\n".join(t for t in texts if t.strip()).strip()
            if not joined:
                # Try research uploads PDF path for compatibility
                return self._ingest_pdf_legacy(path, detection=detection, relative_path=relative_path)

        pages_out: list[dict[str, Any]] = []
        parts: list[str] = []
        for index, page in enumerate(extraction.pages or []):
            if isinstance(page, dict):
                text = str(page.get("text") or "")
                num = int(page.get("page_number") or index + 1)
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
                error_code="PDF_NO_EXTRACTABLE_TEXT",
                skip_reason="PDF has no extractable text (OCR unavailable)",
                unsupported_features=list(extraction.unsupported or ["ocr"]),
                provenance={"relative_path": relative_path, "page_count": len(pages_out)},
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
            },
            unsupported_features=list(extraction.unsupported or []),
            outcome=MemberOutcome.SUCCESS,
        )

    def _ingest_pdf_legacy(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
    ) -> NormalizedArtifact:
        # Bounded: PDFs are typically not multi-GB; still avoid for huge files via settings.
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
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type="application/pdf",
            parser=str(parsed.get("parser") or "pdf"),
            parser_version=str(parsed.get("parser_version") or PARSER_VERSION),
            content_hash=sha256_text(text),
            content=ContentRef(text=text),
            structured_metadata={"structure": parsed.get("structure"), "page_count": parsed.get("page_count")},
            provenance={
                "relative_path": relative_path,
                "page_count": parsed.get("page_count"),
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
    ) -> NormalizedArtifact:
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

    def _ingest_text(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        parser: str,
    ) -> NormalizedArtifact:
        # Stream-decode for large text files
        text = _read_text_streaming(path)
        return NormalizedArtifact(
            source_kind=SourceKind.DOCUMENT if detection.kind == SourceKind.DOCUMENT else SourceKind.PLAIN_TEXT,
            title=Path(relative_path).name,
            relative_path=relative_path,
            mime_type=detection.mime_type or "text/plain",
            parser=parser,
            parser_version=PARSER_VERSION,
            content_hash=sha256_text(text),
            content=ContentRef(text=text),
            provenance={"relative_path": relative_path},
            outcome=MemberOutcome.SUCCESS,
        )


def _read_text_streaming(path: Path, *, chunk_size: int = 1024 * 256) -> str:
    raw = bytearray()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            raw.extend(chunk)
    data = bytes(raw)
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
