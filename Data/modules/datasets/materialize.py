"""Materialize canonical JSONL versions from raw imports (streaming / memory-bounded)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_text

from .canonicalize import canonical_schema_dict, iter_canonical_from_path, iter_canonical_from_sources
from .memory_policy import resolve_dataset_memory_policy
from .scratch import ScratchManager, ScratchSession
from .streaming_io import iter_bounded_text_lines
from .types import CanonicalRecord, DatasetError, DetectedFormat
from .validation import (
    iter_dedupe_identical_ids,
    open_id_integrity_tracker,
    validate_record,
)


def write_canonical_jsonl_stream(
    records: Iterable[CanonicalRecord],
    dest: Path,
    *,
    validate: bool = True,
    max_issues: int = 200,
    check_duplicate_ids: bool = True,
    scratch: ScratchSession | None = None,
    scratch_manager: ScratchManager | None = None,
    scratch_dir: Path | None = None,
    job_id: str = "materialize-id-integrity",
) -> dict[str, Any]:
    """Stream records to canonical JSONL with incremental SHA-256 and atomic publish.

    Never builds an in-memory list of the full corpus or a giant joined string.
    When ``check_duplicate_ids`` is True (default), runs memory-bounded ID
    integrity: conflicting duplicate ids fail validation; identical duplicates
    are skipped (deduped) with provenance.
    """
    ensure_dir(dest.parent)
    tmp = dest.with_name(f"{dest.name}.tmp")
    digest = hashlib.sha256()
    row_count = 0
    written_count = 0
    byte_size = 0
    empty = 0
    all_issues: list[dict[str, Any]] = []
    error_count = 0
    warning_count = 0
    tracker = None
    session: ScratchSession | None = None
    owns_session = False
    tmp_dir = None
    scratch_mgr = scratch_manager
    integrity_summary: dict[str, Any] | None = None

    try:
        if validate and check_duplicate_ids:
            tracker, session, owns_session, tmp_dir = open_id_integrity_tracker(
                scratch=scratch,
                scratch_manager=scratch_mgr,
                scratch_dir=scratch_dir,
                job_id=job_id,
            )

        with tmp.open("wb") as handle:
            if tracker is not None:
                stream = iter_dedupe_identical_ids(records, tracker)
                for rec, issues, keep in stream:
                    if any(i.get("code") == "empty_content" for i in issues):
                        empty += 1
                    for issue in issues:
                        if issue.get("severity") == "warning":
                            warning_count += 1
                        else:
                            error_count += 1
                        if len(all_issues) < max_issues:
                            all_issues.append(issue)
                    row_count += 1
                    if not keep:
                        continue
                    line = json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                    raw = line.encode("utf-8")
                    handle.write(raw)
                    digest.update(raw)
                    byte_size += len(raw)
                    written_count += 1
            else:
                for rec in records:
                    if validate:
                        issues = validate_record(rec, index=row_count)
                        if any(i.get("code") == "empty_content" for i in issues):
                            empty += 1
                        for issue in issues:
                            if issue.get("severity") == "warning":
                                warning_count += 1
                            else:
                                error_count += 1
                            if len(all_issues) < max_issues:
                                all_issues.append(issue)
                    line = json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                    raw = line.encode("utf-8")
                    handle.write(raw)
                    digest.update(raw)
                    byte_size += len(raw)
                    row_count += 1
                    written_count += 1
            handle.flush()
            try:
                os_fsync = getattr(__import__("os"), "fsync", None)
                if os_fsync is not None:
                    os_fsync(handle.fileno())
            except OSError:
                pass
        tmp.replace(dest)
        if tracker is not None:
            tracker.flush()
            integrity_summary = tracker.summary()
            if session is not None:
                session.write_manifest(
                    operation="materialize_id_integrity",
                    stats=dict(integrity_summary),
                )
                if scratch_mgr is not None:
                    scratch_mgr.assert_within_quota(session)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if tracker is not None:
            tracker.close()
            if owns_session and scratch_mgr is not None and session is not None:
                scratch_mgr.cleanup_session(session.job_id)
            if tmp_dir is not None:
                tmp_dir.cleanup()

    validation: dict[str, Any] = {
        "valid": error_count == 0,
        "rowCount": row_count,
        "writtenCount": written_count,
        "errorCount": error_count,
        "warningCount": warning_count,
        "emptyContentCount": empty,
        "issues": all_issues,
        "issuesTruncated": error_count + warning_count > len(all_issues),
        "truncated": error_count + warning_count > len(all_issues),
    }
    if integrity_summary is not None:
        validation["idIntegrity"] = integrity_summary
        validation["duplicateIdConflictCount"] = integrity_summary["duplicateIdConflictCount"]
        validation["identicalDuplicateIdCount"] = integrity_summary["identicalDuplicateIdCount"]
        validation["uniqueIdCount"] = integrity_summary["uniqueIdCount"]
        if integrity_summary["identicalDuplicateIdCount"]:
            validation["provenance"] = {
                "identicalDuplicateIdsDeduped": integrity_summary["identicalDuplicateIdCount"],
                "idIntegrity": {
                    "uniqueIdCount": integrity_summary["uniqueIdCount"],
                    "identicalDuplicateIdCount": integrity_summary["identicalDuplicateIdCount"],
                    "duplicateIdConflictCount": integrity_summary["duplicateIdConflictCount"],
                },
            }

    return {
        "storagePath": str(dest),
        "contentHash": digest.hexdigest(),
        "byteSize": byte_size,
        "rowCount": written_count,
        "inputRowCount": row_count,
        "schema": canonical_schema_dict(),
        "validation": validation,
        "publishState": "PUBLISHED",
    }


def write_canonical_jsonl(records: Iterable[CanonicalRecord], dest: Path) -> tuple[str, int, int]:
    """Compatibility wrapper — streams the iterable; does not join a giant payload string."""
    outcome = write_canonical_jsonl_stream(records, dest, validate=False)
    return outcome["contentHash"], outcome["byteSize"], outcome["rowCount"]


def materialize_from_raw(
    raw_path: Path,
    dest_path: Path,
    *,
    fmt: DetectedFormat | None = None,
    split: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read raw file via iterator, stream-write immutable materialized JSONL."""
    iterator = iter_canonical_from_path(
        raw_path, fmt=fmt, split=split, provenance=provenance
    )
    outcome = write_canonical_jsonl_stream(iterator, dest_path)
    return outcome


def materialize_from_sources(
    sources: list[dict[str, Any]],
    dest_path: Path,
    *,
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """Materialize multiple shards into one coherent canonical JSONL version."""

    def _progressive() -> Iterator[CanonicalRecord]:
        ordered = sorted(sources, key=lambda s: str(s.get("path") or ""))
        total = len(ordered)
        for idx, src in enumerate(ordered):
            path = Path(str(src["path"]))
            fmt_name = src.get("format")
            fmt = DetectedFormat(fmt_name) if fmt_name else None
            split = str(src["split"]) if src.get("split") is not None else None
            provenance = src.get("provenance") if isinstance(src.get("provenance"), dict) else None
            source_name = str(src.get("sourceName") or src.get("relativePath") or path.name)
            if progress_cb:
                progress_cb(
                    {
                        "phase": "materializing",
                        "shardIndex": idx,
                        "shardsTotal": total,
                        "relativePath": source_name,
                    }
                )
            yield from iter_canonical_from_path(
                path,
                fmt=fmt,
                split=split,
                provenance=provenance,
                source_name=source_name,
            )

    return write_canonical_jsonl_stream(_progressive(), dest_path)


def load_materialized_jsonl(
    path: Path,
    *,
    max_bytes: int | None = None,
    allow_large: bool = False,
) -> list[CanonicalRecord]:
    """Load entire materialized file — only for small preview/test use.

    Production handlers must use ``iter_version_records`` / ``iter_materialized_jsonl``.
    Refuses files larger than the configured full-load refuse threshold unless
    ``allow_large=True`` (tests only).
    """
    path = Path(path)
    policy = resolve_dataset_memory_policy()
    refuse_at = int(max_bytes) if max_bytes is not None else policy.full_load_refuse_bytes
    size = path.stat().st_size if path.exists() else 0
    if not allow_large and size > refuse_at:
        raise DatasetError(
            f"Full materialization refused for {size} byte file (limit {refuse_at})",
            code="DATASET_FULL_MATERIALIZATION_REFUSED",
            details={"byteSize": size, "limitBytes": refuse_at, "path": str(path)},
        )
    records: list[CanonicalRecord] = []
    for _idx, line in iter_bounded_text_lines(path, max_record_bytes=policy.max_record_bytes):
        line = line.strip()
        if not line:
            continue
        records.append(CanonicalRecord.from_dict(json.loads(line)))
    return records


def iter_materialized_jsonl(
    path: Path,
    *,
    max_record_bytes: int | None = None,
) -> Iterator[CanonicalRecord]:
    """Stream canonical records from materialized JSONL with bounded line reads."""
    policy = resolve_dataset_memory_policy()
    limit = max_record_bytes if max_record_bytes is not None else policy.max_record_bytes
    for _idx, line in iter_bounded_text_lines(path, max_record_bytes=limit):
        line = line.strip()
        if not line:
            continue
        yield CanonicalRecord.from_dict(json.loads(line))


def iter_version_records(
    storage_path: Path,
    *,
    max_record_bytes: int | None = None,
    format_hint: str | None = None,
) -> Iterator[CanonicalRecord]:
    """Canonical version iterator — no complete corpus list.

    Primary production representation is canonical JSONL. Parquet is supported
    when ``format_hint`` is ``parquet`` or the path suffix is ``.parquet``.
    Heterogeneous text corpora remain JSONL — this does not force Parquet.
    """
    path = Path(storage_path)
    if not path.exists():
        raise DatasetError(f"Version storage missing: {path}", code="no_storage", http_status=404)
    fmt = (format_hint or "").strip().lower()
    if not fmt and path.is_file() and path.suffix.lower() == ".parquet":
        fmt = "parquet"
    if fmt in {"", "jsonl", "canonical_jsonl"}:
        yield from iter_materialized_jsonl(path, max_record_bytes=max_record_bytes)
        return
    if fmt == "parquet":
        from .canonicalize import iter_parquet_canonical

        yield from iter_parquet_canonical(path, source=path.name)
        return
    raise DatasetError(f"Unsupported version storage format: {fmt}", code="unsupported_format")


def records_content_hash(records: Iterable[CanonicalRecord]) -> str:
    """Hash records incrementally — does not join a giant string of the full corpus."""
    digest = hashlib.sha256()
    count = 0
    for rec in records:
        line = json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        digest.update(line.encode("utf-8"))
        count += 1
    if count == 0:
        return sha256_text("")
    return digest.hexdigest()


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
