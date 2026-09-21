from __future__ import annotations

from pathlib import Path
from typing import Any


def run(path: str, *, max_bytes: int = 1_000_000) -> dict[str, Any]:
    """Read a local text file (UTF-8 with replacement).

    Side effect: READ. No network.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    size = target.stat().st_size
    if size > max_bytes:
        raise ValueError(f"File exceeds max_bytes={max_bytes}: {size}")
    data = target.read_bytes()[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "size_bytes": size,
        "encoding": "utf-8",
        "content": text,
        "truncated": size > max_bytes,
    }
