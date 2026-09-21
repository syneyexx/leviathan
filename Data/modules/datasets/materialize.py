"""Materialize canonical JSONL versions from raw imports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file, sha256_text

from .canonicalize import canonical_schema_dict, iter_canonical_from_path
from .types import CanonicalRecord, DetectedFormat


def write_canonical_jsonl(records: list[CanonicalRecord], dest: Path) -> tuple[str, int, int]:
    """Write records as JSONL; return content_hash, byte_size, row_count."""
    ensure_dir(dest.parent)
    lines = [json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True) for rec in records]
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    # Hash of exact bytes written
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        tmp.write_bytes(payload)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return sha256_file(dest), len(payload), len(records)


def materialize_from_raw(
    raw_path: Path,
    dest_path: Path,
    *,
    fmt: DetectedFormat | None = None,
) -> dict[str, Any]:
    """Read raw file, canonicalize, write immutable materialized JSONL."""
    records = list(iter_canonical_from_path(raw_path, fmt=fmt))
    content_hash, byte_size, row_count = write_canonical_jsonl(records, dest_path)
    return {
        "storagePath": str(dest_path),
        "contentHash": content_hash,
        "byteSize": byte_size,
        "rowCount": row_count,
        "schema": canonical_schema_dict(),
        "records": records,
    }


def load_materialized_jsonl(path: Path) -> list[CanonicalRecord]:
    records: list[CanonicalRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(CanonicalRecord.from_dict(json.loads(line)))
    return records


def records_content_hash(records: list[CanonicalRecord]) -> str:
    payload = "\n".join(
        json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True) for r in records
    )
    return sha256_text(payload + ("\n" if records else ""))


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
