"""Export materialized datasets to JSONL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.hashing import sha256_file

from .materialize import load_materialized_jsonl, write_canonical_jsonl
from .types import CanonicalRecord


def export_jsonl(
    records: list[CanonicalRecord],
    dest: Path,
    *,
    split: str | None = None,
) -> dict[str, Any]:
    ensure_dir(dest.parent)
    selected = [r for r in records if split is None or r.split == split]
    content_hash, byte_size, row_count = write_canonical_jsonl(selected, dest)
    return {
        "path": str(dest),
        "contentHash": content_hash,
        "byteSize": byte_size,
        "rowCount": row_count,
        "split": split,
        "format": "jsonl",
    }


def export_version_jsonl(
    version_storage_path: Path,
    dest: Path,
    *,
    split: str | None = None,
) -> dict[str, Any]:
    records = load_materialized_jsonl(version_storage_path)
    return export_jsonl(records, dest, split=split)


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
