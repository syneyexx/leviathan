from __future__ import annotations

from typing import Any

from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import scan_filesystem


def run(
    path: str,
    *,
    recursive: bool = True,
    max_depth: int | None = 32,
    max_entries: int = 10_000,
    follow_symlinks: bool = False,
) -> dict[str, Any]:
    """Bounded recursive filesystem scan."""
    try:
        return scan_filesystem(
            path,
            recursive=recursive,
            max_depth=max_depth,
            max_entries=max_entries,
            follow_symlinks=follow_symlinks,
        )
    except FileIoError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
