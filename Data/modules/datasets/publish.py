"""Atomic data-plane publish + orphan reconciliation."""

from __future__ import annotations

import json
import time
from enum import Enum
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import path_under_root

from .types import DatasetError


class PublishState(str, Enum):
    PREPARED = "PREPARED"
    PUBLISHED = "PUBLISHED"
    REFERENCED = "REFERENCED"
    ORPHANED = "ORPHANED"
    MISSING = "MISSING"
    QUARANTINED = "QUARANTINED"


def prepare_output_path(dest: Path) -> Path:
    """Return a temporary sibling path for streaming writes."""
    ensure_dir(dest.parent)
    return dest.with_name(f".{dest.name}.prepared.tmp")


def publish_atomic(tmp_path: Path, dest: Path, *, expected_hash: str | None = None) -> dict[str, Any]:
    """Fsync-closed temp → hash verify → atomic rename → PUBLISHED."""
    tmp_path = Path(tmp_path)
    dest = Path(dest)
    if not tmp_path.is_file():
        raise DatasetError(f"Prepared output missing: {tmp_path}", code="prepared_missing")
    digest = sha256_file(tmp_path)
    if expected_hash and digest != expected_hash:
        tmp_path.unlink(missing_ok=True)
        raise DatasetError(
            "Prepared output hash mismatch",
            code="NATIVE_OUTPUT_HASH_MISMATCH",
            details={"expected": expected_hash, "actual": digest},
        )
    ensure_dir(dest.parent)
    tmp_path.replace(dest)
    return {
        "path": str(dest),
        "contentHash": digest,
        "byteSize": dest.stat().st_size,
        "publishState": PublishState.PUBLISHED.value,
    }


def reconcile_orphans(
    roots: list[Path],
    *,
    referenced_paths: set[str],
    grace_seconds: int = 3600,
    now: float | None = None,
    max_scan: int = 10_000,
) -> dict[str, Any]:
    """Bounded orphan sweep under governed data-plane roots.

    Never deletes files still referenced by canonical metadata.
    """
    ts = time.time() if now is None else float(now)
    referenced = {str(Path(p).resolve()) for p in referenced_paths}
    orphans: list[dict[str, Any]] = []
    retained: list[str] = []
    scanned = 0
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if scanned >= max_scan:
                break
            if not path.is_file():
                continue
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                scanned += 1
                age = ts - path.stat().st_mtime
                resolved = str(path.resolve())
                if resolved in referenced:
                    retained.append(resolved)
                    continue
                if age < grace_seconds:
                    retained.append(resolved)
                    continue
                try:
                    path.unlink(missing_ok=True)
                    orphans.append({"path": resolved, "action": "deleted_tmp", "ageSeconds": age})
                except OSError as exc:
                    orphans.append({"path": resolved, "action": "delete_failed", "error": str(exc)})
            scanned += 1
    return {
        "scanned": scanned,
        "orphans": orphans,
        "retained": retained[:100],
        "retainedTruncated": len(retained) > 100,
        "truth": {"neverDeletesReferencedFiles": True},
    }


def mark_missing_reference(storage_path: str | Path | None) -> dict[str, Any]:
    if not storage_path:
        return {"publishState": PublishState.MISSING.value, "exists": False}
    path = Path(storage_path)
    exists = path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "publishState": PublishState.REFERENCED.value if exists else PublishState.MISSING.value,
    }
