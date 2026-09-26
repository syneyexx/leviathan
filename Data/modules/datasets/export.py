"""Export materialized datasets to JSONL (streaming)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from Data.modules.common.hashing import sha256_file

from .materialize import iter_materialized_jsonl, write_canonical_jsonl_stream
from .types import CanonicalRecord


def export_jsonl(
    records: Iterable[CanonicalRecord],
    dest: Path,
    *,
    split: str | None = None,
) -> dict[str, Any]:
    """Stream export — never materializes a filtered corpus list."""

    def _filtered() -> Iterable[CanonicalRecord]:
        for rec in records:
            if split is None or rec.split == split:
                yield rec

    outcome = write_canonical_jsonl_stream(_filtered(), dest, validate=False)
    return {
        "path": str(dest),
        "contentHash": outcome["contentHash"],
        "byteSize": outcome["byteSize"],
        "rowCount": outcome["rowCount"],
        "split": split,
        "format": "jsonl",
    }


def export_version_jsonl(
    version_storage_path: Path,
    dest: Path,
    *,
    split: str | None = None,
    max_record_bytes: int | None = None,
) -> dict[str, Any]:
    return export_jsonl(
        iter_materialized_jsonl(version_storage_path, max_record_bytes=max_record_bytes),
        dest,
        split=split,
    )


def preview_jsonl(path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if len(rows) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def verify_export(path: Path) -> str:
    return sha256_file(path)
