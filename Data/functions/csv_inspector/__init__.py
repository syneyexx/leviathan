from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from Data.modules.execution.file_io_thresholds import load_file_io_thresholds


def run(path: str, *, max_rows: int = 20, max_bytes: int | None = None) -> dict[str, Any]:
    """Inspect a CSV: headers, sample rows, rough shape.

    Side effect: READ. Stdlib only — remains cold until loaded.
    Bounded sample inspection only; full parse/profile are separate capabilities.
    """
    thresholds = load_file_io_thresholds()
    effective_max = thresholds.max_inline_csv_bytes if max_bytes is None else int(max_bytes)
    effective_rows = min(int(max_rows), max(thresholds.max_inline_csv_rows * 50, int(max_rows)))
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    size = target.stat().st_size
    if size > effective_max:
        raise ValueError(f"CSV exceeds max_bytes={effective_max}: {size}")

    try:
        csv.field_size_limit(thresholds.csv_field_max_bytes)
    except (OverflowError, AttributeError):
        pass

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
            if index >= effective_rows:
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
        "provenance": {"sample_rows": "sampled", "header": "exact"},
    }
