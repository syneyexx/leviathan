"""Streaming training-dataset hashing — IO_HEAVY / CPU_HEAVY, never GPU_EXCLUSIVE."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable


def _sha256_file(path: Path, *, cancel_check: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancel_check is not None and cancel_check():
                raise RuntimeError("TRAINING_CANCELLED: dataset hash cancelled")
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _stat_sig(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "size": int(st.st_size),
        "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
    }


def hash_training_dataset(
    root: Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
    max_files: int = 100_000,
) -> dict[str, Any]:
    """Hash a file or directory with stable ordering and change detection.

    Returns content_hash (manifest hash for directories) plus before/after stats.
    Detects TRAINING_DATASET_CHANGED when size/mtime differ across the scan.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"dataset path missing: {root}")

    # Reject unsafe symlink escape from governed root when root is a directory.
    if root.is_symlink():
        resolved = root.resolve()
        if not str(resolved).startswith(str(root.parent.resolve())):
            raise ValueError("dataset path symlink escape refused")

    before: dict[str, dict[str, Any]] = {}
    entries: list[Path] = []
    if root.is_file():
        entries = [root]
        before[root.name] = _stat_sig(root)
    else:
        for child in sorted(root.rglob("*")):
            if cancel_check is not None and cancel_check():
                raise RuntimeError("TRAINING_CANCELLED: dataset hash cancelled")
            if child.is_symlink():
                # Skip symlinks that escape the root.
                try:
                    resolved = child.resolve()
                    resolved.relative_to(root.resolve())
                except (ValueError, OSError):
                    continue
            if not child.is_file():
                continue
            rel = str(child.relative_to(root)).replace("\\", "/")
            before[rel] = _stat_sig(child)
            entries.append(child)
            if len(entries) > max_files:
                raise RuntimeError(f"dataset file count exceeds bound ({max_files})")

    files: dict[str, str] = {}
    total_bytes = 0
    for path in entries:
        if cancel_check is not None and cancel_check():
            raise RuntimeError("TRAINING_CANCELLED: dataset hash cancelled")
        rel = path.name if root.is_file() else str(path.relative_to(root)).replace("\\", "/")
        files[rel] = _sha256_file(path, cancel_check=cancel_check)
        total_bytes += int(before[rel]["size"])

    after: dict[str, dict[str, Any]] = {}
    changed = False
    for path in entries:
        rel = path.name if root.is_file() else str(path.relative_to(root)).replace("\\", "/")
        try:
            after[rel] = _stat_sig(path)
        except OSError:
            changed = True
            after[rel] = {"missing": True}
            continue
        if after[rel] != before.get(rel):
            changed = True

    if root.is_file():
        content_hash = next(iter(files.values()))
        manifest_hash = content_hash
    else:
        canonical = json.dumps(
            [{"path": k, "size": before[k]["size"], "hash": files[k]} for k in sorted(files)],
            sort_keys=False,
            separators=(",", ":"),
        )
        manifest_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        content_hash = manifest_hash

    return {
        "path": str(root),
        "content_hash": content_hash,
        "manifest_hash": manifest_hash,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files if len(files) <= 500 else {"_truncated": True, "count": len(files)},
        "changed": changed,
        "pid": os.getpid(),
    }
