from __future__ import annotations

from typing import Any

from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import parse_csv


def run(
    path: str,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Full/streaming CSV parse (external for large files)."""
    try:
        return parse_csv(
            path,
            delimiter=delimiter,
            encoding=encoding,
            max_rows=max_rows,
        )
    except FileIoError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
