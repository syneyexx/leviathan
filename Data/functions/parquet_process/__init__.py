from __future__ import annotations

from typing import Any

from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import process_parquet


def run(path: str, *, mode: str = "inspect") -> dict[str, Any]:
    """Minimal Parquet inspect / row-group processing."""
    try:
        return process_parquet(path, mode=mode)
    except FileIoError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
