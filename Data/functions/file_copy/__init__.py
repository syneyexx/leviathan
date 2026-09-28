from __future__ import annotations

from typing import Any

from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import copy_file


def run(
    source_path: str,
    dest_path: str,
    *,
    overwrite: bool = False,
    preserve_metadata: bool = False,
    compute_hashes: bool = False,
) -> dict[str, Any]:
    """Copy a single file (not a directory tree)."""
    try:
        return copy_file(
            source_path,
            dest_path,
            overwrite=overwrite,
            preserve_metadata=preserve_metadata,
            compute_hashes=compute_hashes,
        )
    except FileIoError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
