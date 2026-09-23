"""Materialize canonical JSONL versions from raw imports (streaming / memory-bounded)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file, sha256_text

from .canonicalize import canonical_schema_dict, iter_canonical_from_path, iter_canonical_from_sources
from .types import CanonicalRecord, DetectedFormat
from .validation import validate_record


def write_canonical_jsonl_stream(
    records: Iterable[CanonicalRecord],
    dest: Path,
    *,
    validate: bool = True,
    max_issues: int = 200,
) -> dict[str, Any]:
    """Stream records to canonical JSONL with incremental SHA-256 and atomic publish.

    Never builds an in-memory list of the full corpus or a giant joined string.
    """
    ensure_dir(dest.parent)
    tmp = dest.with_name(f"{dest.name}.tmp")
    digest = hashlib.sha256()
    row_count = 0
    byte_size = 0
    empty = 0
    all_issues: list[dict[str, Any]] = []

    try:
        with tmp.open("wb") as handle:
            for rec in records:
                if validate:
                    issues = validate_record(rec, index=row_count)
                    if any(i.get("code") == "empty_content" for i in issues):
                        empty += 1
                    for issue in issues:
                        if len(all_issues) < max_issues:
                            all_issues.append(issue)
                line = json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                raw = line.encode("utf-8")
                handle.write(raw)
                digest.update(raw)
                byte_size += len(raw)
                row_count += 1
            handle.flush()
            try:
                os_fsync = getattr(__import__("os"), "fsync", None)
                if os_fsync is not None:
                    os_fsync(handle.fileno())
            except OSError:
                pass
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    errors = [i for i in all_issues if i.get("severity") != "warning"]
    warnings = [i for i in all_issues if i.get("severity") == "warning"]
    validation = {
        "valid": len(errors) == 0,
        "rowCount": row_count,
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "emptyContentCount": empty,
        "issues": all_issues,
        "truncated": row_count > 0 and len(all_issues) >= max_issues,
    }
    return {
        "storagePath": str(dest),
        "contentHash": digest.hexdigest(),
        "byteSize": byte_size,
        "rowCount": row_count,
        "schema": canonical_schema_dict(),
        "validation": validation,
    }


def write_canonical_jsonl(records: list[CanonicalRecord], dest: Path) -> tuple[str, int, int]:
    """Compatibility wrapper — streams the list; does not join a giant payload string."""
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
    # Keep key name used by older callers; do NOT include full records list.
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


def load_materialized_jsonl(path: Path) -> list[CanonicalRecord]:
    """Load entire materialized file — only for small preview/test use."""
    records: list[CanonicalRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(CanonicalRecord.from_dict(json.loads(line)))
    return records


def iter_materialized_jsonl(path: Path) -> Iterator[CanonicalRecord]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield CanonicalRecord.from_dict(json.loads(line))


def records_content_hash(records: list[CanonicalRecord]) -> str:
    payload = "\n".join(
        json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True) for r in records
    )
    return sha256_text(payload + ("\n" if records else ""))


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
