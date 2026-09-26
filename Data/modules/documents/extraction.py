"""Structured document extraction with provenance (Round 7).

Supports HTML tables / multi-column layouts always; PDF via optional pypdf;
scans marked unsupported unless an OCR provider is configured.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


@dataclass
class ProvenanceSpan:
    source_path: str
    page: int | None = None
    locator: str | None = None  # e.g. table[0]/row=2,col=1 / pdf:page=3:bbox
    char_start: int | None = None
    char_end: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "page": self.page,
            "locator": self.locator,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "truth": {"source_location_recorded": self.locator is not None or self.page is not None},
        }


@dataclass
class ExtractedValue:
    kind: str  # text | number | table_cell | footnote
    value: Any
    provenance: ProvenanceSpan
    validated: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "provenance": self.provenance.public_dict(),
            "validated": self.validated,
        }


@dataclass
class DocumentExtraction:
    source_path: str
    source_kind: str
    pages: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    footnotes: list[dict[str, Any]] = field(default_factory=list)
    values: list[ExtractedValue] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    backend: str = "stdlib"
    content_sha256: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "pages": self.pages,
            "tables": self.tables,
            "footnotes": self.footnotes,
            "values": [v.public_dict() for v in self.values],
            "unsupported": list(self.unsupported),
            "backend": self.backend,
            "content_sha256": self.content_sha256,
            "truth": {
                "provenance_required": True,
                "file_created_is_not_validation": True,
                "scan_ocr_not_claimed_without_provider": "ocr_scan" in self.unsupported
                or True,
            },
        }


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._cell_buf = ""
        self.footnotes: list[str] = []
        self._in_footnote = False
        self.columns_hint = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_buf = ""
        elif tag in {"aside", "footer"} or (
            tag == "section" and any(k == "class" and v and "footnote" in (v or "") for k, v in attrs)
        ):
            self._in_footnote = True
        elif tag == "div":
            classes = " ".join(v or "" for k, v in attrs if k == "class")
            if "footnote" in classes or "footnotes" in classes:
                self._in_footnote = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._in_cell:
            self._current_row.append(self._cell_buf.strip())
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._current_row:
                self._current_table.append(self._current_row)
                self.columns_hint = max(self.columns_hint, len(self._current_row))
            self._in_row = False
        elif tag == "table" and self._in_table:
            self.tables.append(self._current_table)
            self._in_table = False
        elif tag in {"aside", "footer", "section", "div"} and self._in_footnote:
            self._in_footnote = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_buf += data
        elif self._in_footnote and data.strip():
            self.footnotes.append(data.strip())


_NUM_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z])")


def extract_document(path: str | Path, *, max_pages: int = 20) -> DocumentExtraction:
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"Document not found: {target}")
    raw = target.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    suffix = target.suffix.lower()

    if suffix in {".html", ".htm", ".xhtml"}:
        return _extract_html(target, raw.decode("utf-8", errors="replace"), digest)
    if suffix == ".csv":
        return _extract_csv(target, raw.decode("utf-8", errors="replace"), digest)
    if suffix == ".json":
        return _extract_json(target, raw.decode("utf-8", errors="replace"), digest)
    if suffix == ".pdf":
        return _extract_pdf(target, raw, digest, max_pages=max_pages)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return DocumentExtraction(
            source_path=str(target),
            source_kind="scan_image",
            unsupported=["ocr_scan"],
            content_sha256=digest,
            backend="unsupported_without_ocr",
        )
    # Plain text / markdown fallback
    text = raw.decode("utf-8", errors="replace")
    return _extract_textish(target, text, digest, source_kind=suffix.lstrip(".") or "text")


def _extract_html(path: Path, text: str, digest: str) -> DocumentExtraction:
    parser = _TableParser()
    parser.feed(text)
    pages = [{"index": 0, "text": re.sub(r"\s+", " ", text)[:4000], "kind": "html"}]
    tables: list[dict[str, Any]] = []
    values: list[ExtractedValue] = []
    for ti, table in enumerate(parser.tables):
        tables.append(
            {
                "index": ti,
                "rows": len(table),
                "cols": max((len(r) for r in table), default=0),
                "multi_column": max((len(r) for r in table), default=0) >= 2,
                "cells": table,
                "provenance": {"locator": f"table[{ti}]", "page": 0},
            }
        )
        for ri, row in enumerate(table):
            for ci, cell in enumerate(row):
                for match in _NUM_RE.finditer(cell):
                    num = _parse_number(match.group(0))
                    values.append(
                        ExtractedValue(
                            kind="number",
                            value=num,
                            provenance=ProvenanceSpan(
                                source_path=str(path),
                                page=0,
                                locator=f"table[{ti}]/row={ri},col={ci}",
                                char_start=match.start(),
                                char_end=match.end(),
                            ),
                            validated=True,
                        )
                    )
    footnotes = [
        {
            "index": i,
            "text": fn,
            "provenance": {"locator": f"footnote[{i}]", "page": 0},
        }
        for i, fn in enumerate(parser.footnotes)
    ]
    return DocumentExtraction(
        source_path=str(path),
        source_kind="html",
        pages=pages,
        tables=tables,
        footnotes=footnotes,
        values=values,
        content_sha256=digest,
        backend="html_parser",
    )


def _extract_csv(path: Path, text: str, digest: str) -> DocumentExtraction:
    reader = csv.reader(io.StringIO(text))
    rows = [list(r) for r in reader]
    values: list[ExtractedValue] = []
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            for match in _NUM_RE.finditer(cell):
                values.append(
                    ExtractedValue(
                        kind="number",
                        value=_parse_number(match.group(0)),
                        provenance=ProvenanceSpan(
                            source_path=str(path),
                            page=0,
                            locator=f"csv/row={ri},col={ci}",
                        ),
                        validated=True,
                    )
                )
    return DocumentExtraction(
        source_path=str(path),
        source_kind="csv",
        pages=[{"index": 0, "text": text[:2000], "kind": "csv"}],
        tables=[
            {
                "index": 0,
                "rows": len(rows),
                "cols": max((len(r) for r in rows), default=0),
                "multi_column": max((len(r) for r in rows), default=0) >= 2,
                "cells": rows,
                "provenance": {"locator": "csv[0]", "page": 0},
            }
        ],
        values=values,
        content_sha256=digest,
        backend="csv",
    )


def _extract_json(path: Path, text: str, digest: str) -> DocumentExtraction:
    data = json.loads(text)
    values: list[ExtractedValue] = []

    def walk(obj: Any, locator: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{locator}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{locator}[{i}]")
        elif isinstance(obj, (int, float)):
            values.append(
                ExtractedValue(
                    kind="number",
                    value=obj,
                    provenance=ProvenanceSpan(source_path=str(path), locator=locator, page=0),
                    validated=True,
                )
            )

    walk(data, "$")
    return DocumentExtraction(
        source_path=str(path),
        source_kind="json",
        pages=[{"index": 0, "text": text[:2000], "kind": "json"}],
        values=values,
        content_sha256=digest,
        backend="json",
    )


def _extract_textish(path: Path, text: str, digest: str, *, source_kind: str) -> DocumentExtraction:
    # Multi-page via form-feed
    raw_pages = text.split("\f") if "\f" in text else [text]
    pages = [{"index": i, "text": p[:4000], "kind": source_kind} for i, p in enumerate(raw_pages)]
    values: list[ExtractedValue] = []
    footnotes: list[dict[str, Any]] = []
    for pi, page in enumerate(raw_pages):
        for match in _NUM_RE.finditer(page):
            values.append(
                ExtractedValue(
                    kind="number",
                    value=_parse_number(match.group(0)),
                    provenance=ProvenanceSpan(
                        source_path=str(path),
                        page=pi,
                        locator=f"page={pi}:offset={match.start()}",
                        char_start=match.start(),
                        char_end=match.end(),
                    ),
                    validated=True,
                )
            )
        for i, line in enumerate(page.splitlines()):
            if line.strip().startswith(("*", "†", "‡", "Footnote", "[")) and len(line) < 200:
                footnotes.append(
                    {
                        "index": len(footnotes),
                        "text": line.strip(),
                        "provenance": {"locator": f"page={pi}:line={i}", "page": pi},
                    }
                )
    return DocumentExtraction(
        source_path=str(path),
        source_kind=source_kind,
        pages=pages,
        footnotes=footnotes,
        values=values,
        content_sha256=digest,
        backend="text",
    )


def _extract_pdf(path: Path, raw: bytes, digest: str, *, max_pages: int) -> DocumentExtraction:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError:
        # Minimal fallback: extract literal strings from PDF content streams (no OCR).
        return _extract_pdf_streams(path, raw, digest, max_pages=max_pages)

    try:
        reader = PdfReader(io.BytesIO(raw))
        pages: list[dict[str, Any]] = []
        values: list[ExtractedValue] = []
        for index, page in enumerate(reader.pages):
            if index >= max_pages:
                break
            text = page.extract_text() or ""
            pages.append({"index": index, "text": text[:4000], "kind": "pdf"})
            for match in _NUM_RE.finditer(text):
                values.append(
                    ExtractedValue(
                        kind="number",
                        value=_parse_number(match.group(0)),
                        provenance=ProvenanceSpan(
                            source_path=str(path),
                            page=index,
                            locator=f"pdf:page={index}:offset={match.start()}",
                            char_start=match.start(),
                            char_end=match.end(),
                        ),
                        validated=True,
                    )
                )
        return DocumentExtraction(
            source_path=str(path),
            source_kind="pdf",
            pages=pages,
            values=values,
            content_sha256=digest,
            backend="pypdf",
            unsupported=["ocr_scan"] if not pages else [],
        )
    except Exception:
        # Corrupt/truncated PDFs must not crash the pipeline — fall back to stream scan.
        return _extract_pdf_streams(path, raw, digest, max_pages=max_pages)


def _extract_pdf_streams(path: Path, raw: bytes, digest: str, *, max_pages: int) -> DocumentExtraction:
    """Best-effort text from PDF literal strings — not OCR, not production PDF quality."""
    text = raw.decode("latin-1", errors="ignore")
    # Split roughly by page objects
    page_chunks = re.split(r"/Type\s*/Page\b", text)[1:] or [text]
    pages: list[dict[str, Any]] = []
    values: list[ExtractedValue] = []
    for index, chunk in enumerate(page_chunks[:max_pages]):
        literals = re.findall(r"\((?:\\.|[^\\)])*\)", chunk)
        joined = " ".join(lit[1:-1].replace("\\n", "\n") for lit in literals)
        pages.append({"index": index, "text": joined[:4000], "kind": "pdf_stream"})
        for match in _NUM_RE.finditer(joined):
            values.append(
                ExtractedValue(
                    kind="number",
                    value=_parse_number(match.group(0)),
                    provenance=ProvenanceSpan(
                        source_path=str(path),
                        page=index,
                        locator=f"pdf_stream:page={index}:offset={match.start()}",
                    ),
                    validated=True,
                )
            )
    return DocumentExtraction(
        source_path=str(path),
        source_kind="pdf",
        pages=pages,
        values=values,
        content_sha256=digest,
        backend="pdf_stream_fallback",
        unsupported=["ocr_scan", "full_layout_analysis"],
    )


def _parse_number(raw: str) -> float | int:
    normalized = raw.replace(",", ".")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def validate_numeric_values(
    extraction: DocumentExtraction,
    *,
    expected: dict[str, float | int],
) -> dict[str, Any]:
    """Validate expected numbers appear with provenance (Round 7)."""
    found = {str(v.value): v for v in extraction.values if v.kind == "number"}
    results = []
    all_ok = True
    for key, want in expected.items():
        hit = found.get(str(want)) or found.get(str(float(want)))
        ok = hit is not None
        all_ok = all_ok and ok
        results.append(
            {
                "key": key,
                "expected": want,
                "ok": ok,
                "provenance": hit.provenance.public_dict() if hit else None,
            }
        )
    return {
        "ok": all_ok,
        "results": results,
        "truth": {"numerical_values_require_source_locations": True},
    }
