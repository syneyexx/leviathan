from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.coding.patch import PatchApplyError as PatchError, apply_unified_diff
from Data.modules.common.atomic import atomic_write_text
from Data.modules.common.hashing import sha256_text


def run(path: str, unified_diff: str) -> dict[str, Any]:
    """Apply a unified diff fail-closed. Side effect: WRITE."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    original = target.read_text(encoding="utf-8")
    hash_before = sha256_text(original)
    try:
        updated = apply_unified_diff(original, unified_diff)
    except PatchError as exc:
        raise ValueError(f"FAILED: patch mismatch — {exc}") from exc
    atomic_write_text(target, updated)
    hash_after = sha256_text(updated)
    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "hash_before": hash_before,
        "hash_after": hash_after,
        "content_hash": hash_after,
        "applied": True,
    }
