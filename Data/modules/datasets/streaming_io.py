"""Bounded record / line readers for dataset data-plane I/O."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Iterator

from .memory_policy import DEFAULT_MAX_RECORD_BYTES, resolve_dataset_memory_policy
from .types import DatasetError

DEFAULT_IO_CHUNK_BYTES = 1024 * 1024


def read_prefix(path: Path | str, n: int) -> bytes:
    """Read at most ``n`` bytes from the start of a file without loading the rest.

    Production large-data paths must use this (or equivalent open+read) instead of
    ``path.read_bytes()[:n]``, which materializes the entire file first.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    if n == 0:
        return b""
    with Path(path).open("rb") as handle:
        return handle.read(n)


def hash_file_streaming(
    path: Path | str,
    *,
    chunk_size: int = DEFAULT_IO_CHUNK_BYTES,
    expected_size: int | None = None,
) -> tuple[str, int]:
    """SHA-256 a file in bounded chunks. Returns (hex_digest, byte_count)."""
    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    if expected_size is not None and total != int(expected_size):
        raise DatasetError(
            f"File size mismatch: expected={expected_size} observed={total}",
            code="SIZE_MISMATCH",
            details={"expectedSize": int(expected_size), "observedSize": total},
        )
    return digest.hexdigest(), total


def stream_copy_and_hash(
    src: Path | str,
    dest: Path | str,
    *,
    chunk_size: int = DEFAULT_IO_CHUNK_BYTES,
    fsync: bool = True,
) -> tuple[str, int]:
    """Copy ``src`` → ``dest`` via unique temp sibling, streaming hash, atomic replace.

    Never holds the full file contents in a Python bytes object.
    Returns (sha256_hex, byte_count).
    """
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dest_path.name}.",
        suffix=".partial",
        dir=str(dest_path.parent),
    )
    tmp_path = Path(tmp_name)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as out, src_path.open("rb") as inp:
            while True:
                chunk = inp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            out.flush()
            if fsync:
                try:
                    os.fsync(out.fileno())
                except OSError:
                    pass
        os.replace(tmp_path, dest_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return digest.hexdigest(), total


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
