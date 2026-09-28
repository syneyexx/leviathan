"""Streaming / chunked filesystem operations for file_io worker + inline bounds."""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.secrets import redact_secrets
from Data.modules.execution.file_io_thresholds import load_file_io_thresholds

from .errors import FileIoError, FileIoErrorCode
from .spill import emit_progress

CancelCheck = Callable[[], bool]
ProgressCb = Callable[[dict[str, Any]], None]


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise FileIoError(FileIoErrorCode.CANCELLED, "Operation cancelled")


def _file_identity(path: Path) -> dict[str, Any]:
    st = path.stat()
    identity: dict[str, Any] = {
        "size_bytes": int(st.st_size),
        "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
    }
    if hasattr(st, "st_ino"):
        identity["inode"] = int(st.st_ino)
    if hasattr(st, "st_dev"):
        identity["device"] = int(st.st_dev)
    return identity


def _changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in ("size_bytes", "mtime_ns", "inode", "device"):
        if key in before and key in after and before[key] != after[key]:
            return True
    return False


def read_text_streaming(
    path: str | Path,
    *,
    max_bytes: int | None = None,
    offset: int = 0,
    length: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Stream a text file; never whole-file ``read_bytes()`` for large payloads."""
    thresholds = load_file_io_thresholds()
    chunk = int(chunk_size or thresholds.stream_chunk_bytes)
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"File not found: {target}")

    before = _file_identity(target)
    size = before["size_bytes"]
    start_off = max(0, int(offset or 0))
    if length is not None:
        end_off = min(size, start_off + max(0, int(length)))
    elif max_bytes is not None:
        end_off = min(size, start_off + max(0, int(max_bytes)))
    else:
        end_off = size

    parts: list[bytes] = []
    bytes_read = 0
    with target.open("rb") as handle:
        if start_off:
            handle.seek(start_off)
        remaining = end_off - start_off
        while remaining > 0:
            _check_cancel(cancel_check)
            to_read = min(chunk, remaining)
            data = handle.read(to_read)
            if not data:
                break
            # Binary refuse on first chunk sample.
            if bytes_read == 0 and b"\x00" in data[:8192]:
                raise FileIoError(
                    FileIoErrorCode.BINARY_REFUSED,
                    f"FAILED: binary file refused: {target}",
                )
            parts.append(data)
            bytes_read += len(data)
            remaining -= len(data)
            emit_progress(
                progress,
                phase="reading",
                bytes_read=bytes_read,
                total_bytes=end_off - start_off,
                percent=round(100.0 * bytes_read / max(1, end_off - start_off), 2),
            )

    raw = b"".join(parts)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileIoError(
            FileIoErrorCode.BINARY_REFUSED,
            f"FAILED: non-text file refused: {target}",
        ) from exc

    text = redact_secrets(text)
    lines = text.splitlines()
    total = len(lines)
    start = 1 if start_line is None else max(1, int(start_line))
    end = total if end_line is None else min(total, int(end_line))
    if end < start - 1:
        end = start - 1
    selected = lines[start - 1 : end]
    numbered = [f"L{idx}|{line}" for idx, line in enumerate(selected, start=start)]
    content = "\n".join(numbered)
    if numbered and text.endswith("\n") and end >= total:
        content += "\n"

    after = _file_identity(target)
    changed = _changed(before, after)
    digest = hashlib.sha256(raw).hexdigest() if raw else hashlib.sha256(b"").hexdigest()

    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "size_bytes": size,
        "encoding": "utf-8",
        "content": content,
        "excerpt": content[:4096] if len(content) > 4096 else content,
        "line_count": total,
        "start_line": start,
        "end_line": end,
        "offset": start_off,
        "length": bytes_read,
        "truncated": (end_off - start_off) < (size - start_off) or (end < total),
        "content_hash": digest,
        "identity_before": before,
        "identity_after": after,
        "stability": "CHANGED_DURING_READ" if changed else "STABLE",
        "bytes_read": bytes_read,
        "artifact_ref": None,
    }


def write_text_streaming(
    path: str | Path,
    content: str | None = None,
    *,
    content_path: str | Path | None = None,
    create_parents: bool = True,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Atomic write via temp sibling → fsync → replace. Supports staged content_path."""
    thresholds = load_file_io_thresholds()
    chunk = int(chunk_size or thresholds.stream_chunk_bytes)
    target = Path(path).expanduser()
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)

    hash_before = None
    if target.is_file():
        try:
            h = hashlib.sha256()
            with target.open("rb") as existing:
                while True:
                    _check_cancel(cancel_check)
                    block = existing.read(chunk)
                    if not block:
                        break
                    h.update(block)
            hash_before = h.hexdigest()
        except OSError:
            hash_before = None

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    digest = hashlib.sha256()
    bytes_written = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            if content_path is not None:
                source = Path(content_path)
                with source.open("rb") as src:
                    while True:
                        _check_cancel(cancel_check)
                        block = src.read(chunk)
                        if not block:
                            break
                        handle.write(block)
                        digest.update(block)
                        bytes_written += len(block)
                        emit_progress(
                            progress,
                            phase="writing",
                            bytes_written=bytes_written,
                            percent=None,
                        )
            else:
                data = (content if content is not None else "").encode("utf-8")
                view = memoryview(data)
                pos = 0
                total = len(data)
                while pos < total:
                    _check_cancel(cancel_check)
                    block = bytes(view[pos : pos + chunk])
                    handle.write(block)
                    digest.update(block)
                    pos += len(block)
                    bytes_written += len(block)
                    emit_progress(
                        progress,
                        phase="writing",
                        bytes_written=bytes_written,
                        total_bytes=total,
                        percent=round(100.0 * bytes_written / max(1, total), 2),
                    )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except FileIoError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise FileIoError(FileIoErrorCode.FILE_COPY_FAILED, f"Write failed: {exc}") from exc

    hash_after = digest.hexdigest()
    emit_progress(progress, phase="completed", bytes_written=bytes_written, percent=100.0)
    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "bytes_written": bytes_written,
        "hash_before": hash_before,
        "hash_after": hash_after,
        "content_hash": hash_after,
        "created": hash_before is None,
    }


def copy_file(
    source_path: str | Path,
    dest_path: str | Path,
    *,
    overwrite: bool = False,
    preserve_metadata: bool = False,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    chunk_size: int | None = None,
    compute_hashes: bool = False,
) -> dict[str, Any]:
    """Stream copy a single file (not directories). Atomic dest promotion."""
    thresholds = load_file_io_thresholds()
    chunk = int(chunk_size or thresholds.stream_chunk_bytes)
    src = Path(source_path).expanduser()
    dest = Path(dest_path).expanduser()
    if not src.is_file():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"Source not found: {src}")
    try:
        if src.resolve() == dest.resolve():
            raise FileIoError(
                FileIoErrorCode.INVALID_ARGUMENT,
                "source_path and dest_path must differ",
            )
    except FileIoError:
        raise
    except OSError:
        if os.path.normcase(str(src)) == os.path.normcase(str(dest)):
            raise FileIoError(
                FileIoErrorCode.INVALID_ARGUMENT,
                "source_path and dest_path must differ",
            )

    if dest.exists() and not overwrite:
        raise FileIoError(FileIoErrorCode.FILE_COPY_FAILED, f"Destination exists: {dest}")
    if dest.exists() and dest.is_dir():
        raise FileIoError(FileIoErrorCode.FILE_COPY_FAILED, f"Destination is a directory: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    before = _file_identity(src)
    size = before["size_bytes"]
    src_hash = hashlib.sha256() if compute_hashes else None
    dst_hash = hashlib.sha256() if compute_hashes else None

    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    tmp_path = Path(tmp_name)
    bytes_copied = 0
    try:
        with src.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            while True:
                _check_cancel(cancel_check)
                block = reader.read(chunk)
                if not block:
                    break
                writer.write(block)
                if src_hash is not None:
                    src_hash.update(block)
                    dst_hash.update(block)  # type: ignore[union-attr]
                bytes_copied += len(block)
                emit_progress(
                    progress,
                    phase="copying",
                    bytes_copied=bytes_copied,
                    total_bytes=size,
                    percent=round(100.0 * bytes_copied / max(1, size), 2),
                )
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(tmp_path, dest)
        if preserve_metadata:
            try:
                shutil.copystat(src, dest, follow_symlinks=True)
            except OSError:
                pass
    except FileIoError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise FileIoError(FileIoErrorCode.FILE_COPY_FAILED, f"Copy failed: {exc}") from exc

    after = _file_identity(src)
    changed = _changed(before, after)
    result: dict[str, Any] = {
        "source_path": str(src),
        "dest_path": str(dest.resolve()) if dest.exists() else str(dest),
        "bytes_copied": bytes_copied,
        "overwrite": overwrite,
        "preserve_metadata": preserve_metadata,
        "stability": "CHANGED_DURING_READ" if changed else "STABLE",
        "identity_before": before,
        "identity_after": after,
    }
    if compute_hashes and src_hash is not None and dst_hash is not None:
        result["source_hash"] = src_hash.hexdigest()
        result["dest_hash"] = dst_hash.hexdigest()
    emit_progress(progress, phase="completed", bytes_copied=bytes_copied, percent=100.0)
    return result


def hash_file(
    path: str | Path,
    *,
    algorithm: str = "sha256",
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    """Streaming content hash with mutation detection."""
    if algorithm.lower() not in {"sha256", "sha-256"}:
        raise FileIoError(
            FileIoErrorCode.INVALID_ARGUMENT,
            f"Unsupported hash algorithm: {algorithm} (canonical: sha256)",
        )
    thresholds = load_file_io_thresholds()
    chunk = int(chunk_size or thresholds.stream_chunk_bytes)
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"File not found: {target}")

    before = _file_identity(target)
    size = before["size_bytes"]
    digest = hashlib.sha256()
    bytes_hashed = 0
    try:
        with target.open("rb") as handle:
            while True:
                _check_cancel(cancel_check)
                block = handle.read(chunk)
                if not block:
                    break
                digest.update(block)
                bytes_hashed += len(block)
                emit_progress(
                    progress,
                    phase="hashing",
                    bytes_hashed=bytes_hashed,
                    total_bytes=size,
                    percent=round(100.0 * bytes_hashed / max(1, size), 2),
                )
    except FileIoError:
        raise
    except OSError as exc:
        raise FileIoError(FileIoErrorCode.FILE_HASH_FAILED, str(exc)) from exc

    after = _file_identity(target)
    changed = _changed(before, after)
    status = "CHANGED_DURING_READ" if changed else "STABLE"
    emit_progress(progress, phase="completed", bytes_hashed=bytes_hashed, percent=100.0)
    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "algorithm": "sha256",
        "hash": digest.hexdigest() if not changed else None,
        "content_hash": digest.hexdigest() if not changed else None,
        "bytes_hashed": bytes_hashed,
        "size_bytes": size,
        "status": status,
        "stability": status,
        "identity_before": before,
        "identity_after": after,
        "truth": {
            "stable_hash": not changed,
            "mutation_detected": changed,
        },
    }


def _csv_field_size_limit(limit: int) -> None:
    try:
        csv.field_size_limit(limit)
    except (OverflowError, AttributeError):
        pass


def parse_csv(
    path: str | Path,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    max_rows: int | None = None,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Streaming CSV parse — does not materialize millions of rows."""
    thresholds = load_file_io_thresholds()
    _csv_field_size_limit(thresholds.csv_field_max_bytes)
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"File not found: {target}")
    before = _file_identity(target)
    size = before["size_bytes"]

    headers: list[str] = []
    row_count = 0
    malformed = 0
    column_count = 0
    sample_rows: list[list[str]] = []
    bytes_read = 0

    try:
        with target.open("r", encoding=encoding, errors="replace", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            if delimiter:
                dialect = csv.excel
                dialect.delimiter = delimiter  # type: ignore[attr-defined]
            else:
                try:
                    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
                except csv.Error:
                    dialect = csv.excel
            reader = csv.reader(handle, dialect)
            for index, row in enumerate(reader):
                _check_cancel(cancel_check)
                if index == 0:
                    headers = list(row)
                    column_count = len(headers)
                    continue
                row_count += 1
                if len(row) != column_count and column_count:
                    malformed += 1
                if len(sample_rows) < 20:
                    sample_rows.append(row)
                if max_rows is not None and row_count >= int(max_rows):
                    break
                if index % 256 == 0:
                    try:
                        bytes_read = handle.tell()
                    except OSError:
                        bytes_read = 0
                    emit_progress(
                        progress,
                        phase="parsing",
                        rows_processed=row_count,
                        bytes_read=bytes_read,
                        total_bytes=size,
                    )
            try:
                bytes_read = handle.tell()
            except OSError:
                pass
    except FileIoError:
        raise
    except Exception as exc:
        raise FileIoError(FileIoErrorCode.CSV_PARSE_FAILED, str(exc)) from exc

    after = _file_identity(target)
    return {
        "path": str(target),
        "size_bytes": size,
        "header": headers,
        "column_count": column_count,
        "row_count": row_count,
        "malformed_rows": malformed,
        "sample_rows": sample_rows,
        "dialect": getattr(dialect, "delimiter", delimiter or ","),
        "encoding": encoding,
        "bytes_read": bytes_read,
        "stability": "CHANGED_DURING_READ" if _changed(before, after) else "STABLE",
        "provenance": {"row_count": "exact" if max_rows is None else "sampled"},
    }


def profile_csv(
    path: str | Path,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    exact_distinct_max: int = 10_000,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Streaming CSV profile with online stats (no full value retention)."""
    thresholds = load_file_io_thresholds()
    _csv_field_size_limit(thresholds.csv_field_max_bytes)
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"File not found: {target}")
    before = _file_identity(target)
    size = before["size_bytes"]

    headers: list[str] = []
    null_counts: list[int] = []
    distinct_sets: list[set[str]] = []
    distinct_overflow: list[bool] = []
    numeric_min: list[float | None] = []
    numeric_max: list[float | None] = []
    numeric_sum: list[float] = []
    numeric_count: list[int] = []
    row_count = 0
    malformed = 0
    sample_rows: list[list[str]] = []
    bytes_read = 0
    dialect: Any = csv.excel

    try:
        with target.open("r", encoding=encoding, errors="replace", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            if delimiter:
                dialect = csv.excel
                dialect.delimiter = delimiter  # type: ignore[misc]
            else:
                try:
                    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
                except csv.Error:
                    dialect = csv.excel
            reader = csv.reader(handle, dialect)
            for index, row in enumerate(reader):
                _check_cancel(cancel_check)
                if index == 0:
                    headers = list(row)
                    n = len(headers)
                    null_counts = [0] * n
                    distinct_sets = [set() for _ in range(n)]
                    distinct_overflow = [False] * n
                    numeric_min = [None] * n
                    numeric_max = [None] * n
                    numeric_sum = [0.0] * n
                    numeric_count = [0] * n
                    continue
                row_count += 1
                if len(row) != len(headers):
                    malformed += 1
                if len(sample_rows) < 10:
                    sample_rows.append(row)
                for i, cell in enumerate(row):
                    if i >= len(headers):
                        break
                    if cell is None or str(cell).strip() == "":
                        null_counts[i] += 1
                        continue
                    text = str(cell)
                    if not distinct_overflow[i]:
                        if len(distinct_sets[i]) < exact_distinct_max:
                            distinct_sets[i].add(text)
                        else:
                            distinct_overflow[i] = True
                    try:
                        num = float(text)
                    except ValueError:
                        continue
                    numeric_count[i] += 1
                    numeric_sum[i] += num
                    if numeric_min[i] is None or num < numeric_min[i]:  # type: ignore[operator]
                        numeric_min[i] = num
                    if numeric_max[i] is None or num > numeric_max[i]:  # type: ignore[operator]
                        numeric_max[i] = num
                if index % 256 == 0:
                    try:
                        bytes_read = handle.tell()
                    except OSError:
                        bytes_read = 0
                    emit_progress(
                        progress,
                        phase="profiling",
                        rows_processed=row_count,
                        bytes_read=bytes_read,
                        total_bytes=size,
                    )
            try:
                bytes_read = handle.tell()
            except OSError:
                pass
    except FileIoError:
        raise
    except Exception as exc:
        raise FileIoError(FileIoErrorCode.CSV_PROFILE_FAILED, str(exc)) from exc

    columns = []
    for i, name in enumerate(headers):
        distinct_n = len(distinct_sets[i]) if i < len(distinct_sets) else 0
        overflow = distinct_overflow[i] if i < len(distinct_overflow) else False
        col: dict[str, Any] = {
            "name": name,
            "null_count": {"value": null_counts[i], "provenance": "exact"},
            "distinct_count": {
                "value": distinct_n,
                "provenance": "approximate" if overflow else "exact",
            },
        }
        if numeric_count[i]:
            col["min"] = {"value": numeric_min[i], "provenance": "exact"}
            col["max"] = {"value": numeric_max[i], "provenance": "exact"}
            col["mean"] = {
                "value": numeric_sum[i] / numeric_count[i],
                "provenance": "exact",
            }
            col["numeric_count"] = {"value": numeric_count[i], "provenance": "exact"}
        columns.append(col)

    after = _file_identity(target)
    return {
        "path": str(target),
        "size_bytes": size,
        "row_count": {"value": row_count, "provenance": "exact"},
        "column_count": {"value": len(headers), "provenance": "exact"},
        "columns": columns,
        "invalid_rows": {"value": malformed, "provenance": "exact"},
        "sample": {"value": sample_rows, "provenance": "sampled"},
        "encoding": encoding,
        "dialect": getattr(dialect, "delimiter", ","),
        "bytes_read": bytes_read,
        "stability": "CHANGED_DURING_READ" if _changed(before, after) else "STABLE",
        "identity_before": before,
        "identity_after": after,
    }


def process_parquet(
    path: str | Path,
    *,
    mode: str = "inspect",
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Minimal Parquet inspect / row-group walk. No fake analytics subsystem."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"File not found: {target}")
    try:
        import pyarrow.parquet as pq  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise FileIoError(
            FileIoErrorCode.PARQUET_UNAVAILABLE,
            f"Parquet backend unavailable: {exc}",
        ) from exc

    before = _file_identity(target)
    try:
        pf = pq.ParquetFile(str(target))
        meta = pf.metadata
        schema = pf.schema_arrow
        row_groups = int(meta.num_row_groups) if meta is not None else 0
        num_rows = int(meta.num_rows) if meta is not None else 0
        columns = [field.name for field in schema]
        if mode == "inspect":
            emit_progress(progress, phase="completed", row_groups_processed=0, total_row_groups=row_groups)
            return {
                "path": str(target),
                "mode": "inspect",
                "row_groups": row_groups,
                "num_rows": num_rows,
                "columns": columns,
                "schema": str(schema),
                "size_bytes": before["size_bytes"],
                "stability": "STABLE",
                "provenance": {"num_rows": "exact", "columns": "exact"},
            }

        # Streaming row-group touch (count only — no full materialization).
        processed = 0
        for i in range(row_groups):
            _check_cancel(cancel_check)
            _ = pf.read_row_group(i, columns=columns[:1] if columns else None)
            processed += 1
            emit_progress(
                progress,
                phase="processing",
                row_groups_processed=processed,
                total_row_groups=row_groups,
                percent=round(100.0 * processed / max(1, row_groups), 2),
            )
        after = _file_identity(target)
        return {
            "path": str(target),
            "mode": mode,
            "row_groups": row_groups,
            "row_groups_processed": processed,
            "num_rows": num_rows,
            "columns": columns,
            "size_bytes": before["size_bytes"],
            "stability": "CHANGED_DURING_READ" if _changed(before, after) else "STABLE",
        }
    except FileIoError:
        raise
    except Exception as exc:
        raise FileIoError(FileIoErrorCode.PARQUET_PROCESS_FAILED, str(exc)) from exc


def scan_filesystem(
    root: str | Path,
    *,
    recursive: bool = True,
    max_depth: int | None = 32,
    max_entries: int = 10_000,
    follow_symlinks: bool = False,
    cancel_check: CancelCheck | None = None,
    progress: ProgressCb | None = None,
    exclude_names: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Bounded recursive filesystem scan with cycle prevention."""
    base = Path(root).expanduser()
    if not base.exists():
        raise FileIoError(FileIoErrorCode.FILE_NOT_FOUND, f"Path not found: {base}")
    try:
        base_resolved = base.resolve()
    except OSError as exc:
        raise FileIoError(FileIoErrorCode.FILE_ACCESS_DENIED, str(exc)) from exc

    deny = exclude_names or frozenset({"HADES", "editor", ".git", "node_modules", "__pycache__"})
    entries: list[dict[str, Any]] = []
    seen_dirs: set[tuple[int, int]] = set()
    entries_scanned = 0
    bytes_discovered = 0
    truncated = False
    started = time.monotonic()

    def _dir_key(path: Path) -> tuple[int, int] | None:
        try:
            st = path.stat()
            return (int(getattr(st, "st_dev", 0)), int(getattr(st, "st_ino", hash(str(path)))))
        except OSError:
            return None

    def _walk(current: Path, depth: int) -> None:
        nonlocal entries_scanned, bytes_discovered, truncated
        _check_cancel(cancel_check)
        if truncated:
            return
        if max_depth is not None and depth > int(max_depth):
            return
        try:
            children = sorted(current.iterdir(), key=lambda p: str(p).lower())
        except OSError:
            return
        for child in children:
            _check_cancel(cancel_check)
            if truncated:
                return
            name = child.name
            if name in deny or name.startswith(".") and name in {".git"}:
                continue
            entries_scanned += 1
            try:
                if child.is_symlink() and not follow_symlinks:
                    # Record symlink but do not follow outside root.
                    rel = str(child.relative_to(base_resolved))
                    entries.append({"path": rel, "type": "symlink", "size": 0})
                    if len(entries) >= max_entries:
                        truncated = True
                        return
                    continue
                if child.is_symlink() and follow_symlinks:
                    try:
                        resolved = child.resolve()
                        resolved.relative_to(base_resolved)
                    except (ValueError, OSError):
                        raise FileIoError(
                            FileIoErrorCode.SYMLINK_ESCAPE,
                            f"Symlink escapes scan root: {child}",
                        )
                if child.is_dir():
                    key = _dir_key(child)
                    if key is not None:
                        if key in seen_dirs:
                            continue
                        seen_dirs.add(key)
                    rel = str(child.relative_to(base_resolved))
                    entries.append({"path": rel, "type": "dir", "size": 0})
                    if len(entries) >= max_entries:
                        truncated = True
                        return
                    if recursive:
                        _walk(child, depth + 1)
                elif child.is_file():
                    try:
                        size = int(child.stat().st_size)
                    except OSError:
                        size = 0
                    bytes_discovered += size
                    rel = str(child.relative_to(base_resolved))
                    entries.append({"path": rel, "type": "file", "size": size})
                    if len(entries) >= max_entries:
                        truncated = True
                        return
            except FileIoError:
                raise
            except OSError:
                continue
            emit_progress(
                progress,
                phase="scanning",
                entries_scanned=entries_scanned,
                bytes_discovered=bytes_discovered,
                entries_returned=len(entries),
            )

    root_key = _dir_key(base_resolved)
    if root_key is not None:
        seen_dirs.add(root_key)
    if base_resolved.is_file():
        entries.append(
            {
                "path": base_resolved.name,
                "type": "file",
                "size": int(base_resolved.stat().st_size),
            }
        )
        entries_scanned = 1
        bytes_discovered = entries[0]["size"]
    else:
        _walk(base_resolved, 0)

    if truncated:
        # Soft limit — report; callers may treat as limit exceeded for hard policies.
        pass

    duration_ms = (time.monotonic() - started) * 1000
    return {
        "root": str(base_resolved),
        "recursive": recursive,
        "max_depth": max_depth,
        "max_entries": max_entries,
        "entries": entries,
        "entries_scanned": entries_scanned,
        "entries_returned": len(entries),
        "bytes_discovered": bytes_discovered,
        "truncated": truncated,
        "duration_ms": round(duration_ms, 2),
        "follow_symlinks": follow_symlinks,
        "limit_exceeded": truncated,
    }
