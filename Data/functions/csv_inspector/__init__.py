from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def run(path: str, *, max_rows: int = 20, max_bytes: int = 2_000_000) -> dict[str, Any]:
    """Inspect a CSV: headers, sample rows, rough shape.

    Side effect: READ. Stdlib only — remains cold until loaded.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    size = target.stat().st_size
    if size > max_bytes:
        raise ValueError(f"CSV exceeds max_bytes={max_bytes}: {size}")

    with target.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(handle, dialect)
        rows = []
        for index, row in enumerate(reader):
            rows.append(row)
            if index >= max_rows:
                break

    headers = rows[0] if rows else []
    body = rows[1:] if len(rows) > 1 else []
    return {
        "path": str(target),
        "size_bytes": size,
        "header": headers,
        "column_count": len(headers),
        "sample_row_count": len(body),
        "sample_rows": body,
        "dialect": getattr(dialect, "delimiter", ","),
    }
