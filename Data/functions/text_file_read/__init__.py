from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from Data.modules.execution.file_io_thresholds import load_file_io_thresholds
from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import read_text_streaming


def run(
    path: str,
    *,
    max_bytes: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    offset: int = 0,
    length: int | None = None,
) -> dict[str, Any]:
    """Read a local text file with optional line/byte range (chunked).

    Output lines are always formatted as ``L{n}|{text}``.
    Binary files (NUL in sample) → FAILED-style error.
    Secret-looking content is redacted before return.

    Inline callers keep the historical max_bytes ceiling. The ``file_io`` worker
    may stream larger files (bounded by explicit length/max_bytes when provided,
    otherwise the full file with result spill handled by ExecutionGateway).
    """
    thresholds = load_file_io_thresholds()
    in_file_io = (os.environ.get("LEVIATHAN_WORKER_POOL") or "").strip() == "file_io" or (
        os.environ.get("LEVIATHAN_WORKER_ID") or ""
    ).startswith("file_io")
    effective_max = thresholds.max_inline_read_bytes if max_bytes is None else int(max_bytes)
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    size = target.stat().st_size

    # Preserve historical refuse-when-over-max for API/inline small ceilings.
    if (
        not in_file_io
        and length is None
        and start_line is None
        and end_line is None
        and offset == 0
        and size > effective_max
    ):
        raise ValueError(f"File exceeds max_bytes={effective_max}: {size}")

    read_max = None if in_file_io and max_bytes is None and length is None else effective_max
    try:
        result = read_text_streaming(
            target,
            max_bytes=read_max,
            offset=offset,
            length=length,
            start_line=start_line,
            end_line=end_line,
        )
    except FileIoError as exc:
        raise ValueError(exc.message) from exc
    return result
