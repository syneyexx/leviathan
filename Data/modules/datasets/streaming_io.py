"""Bounded record / line readers for dataset data-plane I/O."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .memory_policy import DEFAULT_MAX_RECORD_BYTES, resolve_dataset_memory_policy
from .types import DatasetError


def iter_bounded_text_lines(
    path: Path,
    *,
    max_record_bytes: int | None = None,
    encoding: str = "utf-8",
) -> Iterator[tuple[int, str]]:
    """Yield (1-based line_index, line_without_newline) with per-line byte bound.

    Raises DatasetError(code=RECORD_TOO_LARGE) without retaining the oversized payload.
    """
    limit = int(max_record_bytes) if max_record_bytes is not None else resolve_dataset_memory_policy().max_record_bytes
    if limit <= 0:
        limit = DEFAULT_MAX_RECORD_BYTES

    with Path(path).open("rb") as handle:
        line_index = 0
        while True:
            line_index += 1
            buf = bytearray()
            exceeded = False
            while True:
                chunk = handle.read(1)
                if not chunk:
                    if buf:
                        if exceeded:
                            raise DatasetError(
                                f"Record exceeds max_record_bytes={limit} at line {line_index}",
                                code="RECORD_TOO_LARGE",
                                details={
                                    "lineIndex": line_index,
                                    "maxRecordBytes": limit,
                                    "observedExceedsMax": True,
                                },
                            )
                        text = buf.decode(encoding, errors="replace")
                        if text.endswith("\r"):
                            text = text[:-1]
                        yield line_index, text
                    return
                if chunk == b"\n":
                    break
                if not exceeded:
                    if len(buf) >= limit:
                        exceeded = True
                        buf.clear()
                    else:
                        buf.extend(chunk)
            if exceeded:
                raise DatasetError(
                    f"Record exceeds max_record_bytes={limit} at line {line_index}",
                    code="RECORD_TOO_LARGE",
                    details={
                        "lineIndex": line_index,
                        "maxRecordBytes": limit,
                        "observedExceedsMax": True,
                    },
                )
            text = buf.decode(encoding, errors="replace")
            if text.endswith("\r"):
                text = text[:-1]
            yield line_index, text


def iter_bounded_paragraphs(
    path: Path,
    *,
    max_record_bytes: int | None = None,
    encoding: str = "utf-8",
) -> Iterator[tuple[int, str]]:
    """Stream paragraphs separated by blank lines; bound each paragraph size."""
    limit = int(max_record_bytes) if max_record_bytes is not None else resolve_dataset_memory_policy().max_record_bytes
    if limit <= 0:
        limit = DEFAULT_MAX_RECORD_BYTES

    paragraph_index = 0
    buf = bytearray()
    exceeded = False

    def _emit() -> tuple[int, str] | None:
        nonlocal paragraph_index, buf, exceeded
        if exceeded:
            raise DatasetError(
                f"Paragraph exceeds max_record_bytes={limit} at paragraph {paragraph_index + 1}",
                code="RECORD_TOO_LARGE",
                details={
                    "paragraphIndex": paragraph_index + 1,
                    "maxRecordBytes": limit,
                    "observedExceedsMax": True,
                },
            )
        text = buf.decode(encoding, errors="replace").strip()
        buf = bytearray()
        if not text:
            return None
        paragraph_index += 1
        return paragraph_index, text

    with Path(path).open("rb") as handle:
        blank_run = 0
        while True:
            chunk = handle.read(1)
            if not chunk:
                emitted = _emit()
                if emitted is not None:
                    yield emitted
                return
            if chunk == b"\n":
                blank_run += 1
                if blank_run >= 2:
                    emitted = _emit()
                    if emitted is not None:
                        yield emitted
                    blank_run = 0
                    continue
                if not exceeded:
                    if len(buf) < limit:
                        buf.extend(chunk)
                    else:
                        exceeded = True
                        buf.clear()
                continue
            blank_run = 0
            if not exceeded:
                if len(buf) >= limit:
                    exceeded = True
                    buf.clear()
                else:
                    buf.extend(chunk)
