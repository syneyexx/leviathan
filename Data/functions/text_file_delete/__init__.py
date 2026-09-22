from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_file


def run(path: str) -> dict[str, Any]:
    """Delete a local file. Side effect: DELETE/DESTRUCTIVE."""
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"Refusing to delete directory: {target}")
    content_hash = sha256_file(target) if target.is_file() else None
    size = target.stat().st_size
    target.unlink()
    return {
        "path": str(target),
        "deleted": True,
        "size_bytes": size,
        "hash_before": content_hash,
    }
