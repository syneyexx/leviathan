from __future__ import annotations

from typing import Any

from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import profile_csv


def run(
    path: str,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    exact_distinct_max: int = 10_000,
) -> dict[str, Any]:
    """Streaming CSV profile with exact/approximate provenance."""
    try:
        return profile_csv(
            path,
            delimiter=delimiter,
            encoding=encoding,
            exact_distinct_max=exact_distinct_max,
        )
    except FileIoError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
