from __future__ import annotations

from typing import Any

from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import hash_file


def run(path: str, *, algorithm: str = "sha256") -> dict[str, Any]:
    """Streaming SHA-256 (canonical) of a local file."""
    try:
        return hash_file(path, algorithm=algorithm)
    except FileIoError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
