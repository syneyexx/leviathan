from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text
from Data.modules.common.hashing import sha256_text


def run(
    path: str,
    content: str,
    *,
    create_parents: bool = True,
) -> dict[str, Any]:
    """Write UTF-8 text to a local file (atomic). Side effect: WRITE."""
    target = Path(path).expanduser()
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    hash_before = None
    if target.is_file():
        try:
            hash_before = sha256_text(target.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            hash_before = None
    atomic_write_text(target, content if content is not None else "")
    hash_after = sha256_text(content if content is not None else "")
    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "bytes_written": len((content or "").encode("utf-8")),
        "hash_before": hash_before,
        "hash_after": hash_after,
        "content_hash": hash_after,
        "created": hash_before is None,
    }
