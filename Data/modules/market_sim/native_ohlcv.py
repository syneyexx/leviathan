"""Optional native OHLCV validation via ``market.ohlcv_validate``.

Thin helper for MarketDataStore / OHLCV paths. Does **not** rewrite MarketSim,
RiskGuard, or portfolio logic — Python streaming validation remains the default.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_file
from Data.modules.workers.native_compute import (
    build_task_document,
    resolve_native_binary,
    run_native_task,
)

from .ohlcv import OhlcvValidation, REQUIRED_OHLCV_COLUMNS, _parquet_available, validate_ohlcv_file


def _input_format_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".txt"}:
        return "csv"
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    if suffix == ".parquet":
        return "parquet"
    return "csv"


def try_native_ohlcv_validate(
    path: Path | str,
    *,
    binary: Path | None = None,
    work_dir: Path | None = None,
) -> OhlcvValidation | None:
    """Run ``market.ohlcv_validate`` when the native binary is available.

    Returns ``None`` when the binary is missing or the native run fails hard
    (caller should fall back to Python streaming validation).
    Soft validation failures (bad OHLC / duplicates) still return an
    ``OhlcvValidation`` with ``ok=False``.
    """
    path = Path(path)
    bin_path = binary or resolve_native_binary()
    if bin_path is None:
        return None
    if not path.is_file():
        return OhlcvValidation(
            ok=False,
            bar_count=0,
            start_ts=None,
            end_ts=None,
            content_hash="",
            byte_size=0,
            error="file not found",
            parquet_available=_parquet_available(),
        )

    byte_size = path.stat().st_size
    try:
        content_hash = sha256_file(path)
    except OSError:
        content_hash = ""

    root = path.resolve().parent
    with tempfile.TemporaryDirectory(prefix="leviathan-ohlcv-native-") as tmp:
        tmp_path = Path(tmp)
        out = tmp_path / "ohlcv_validate.json"
        task = build_task_document(
            task_id=f"ohlcv-{uuid.uuid4().hex[:12]}",
            operation="market.ohlcv_validate",
            input_path=path,
            temporary_path=out,
            allowed_roots=[str(root), str(tmp_path)],
            input_format=_input_format_for(path),
        )
        result = run_native_task(
            task,
            binary=bin_path,
            work_dir=work_dir or tmp_path / "work",
        )
        if not result.ok and result.error_code in {
            "NATIVE_BINARY_MISSING",
            "NATIVE_UNSUPPORTED_OPERATION",
            "NATIVE_PROTOCOL_MISMATCH",
        }:
            return None
        report: dict[str, Any] = {}
        if result.receipt and isinstance(result.receipt.get("result"), dict):
            report = dict(result.receipt["result"])
        elif out.is_file():
            import json

            report = json.loads(out.read_text(encoding="utf-8"))
        if not report and not result.ok:
            return None
        ok = bool(report.get("ok", report.get("valid", False)))
        return OhlcvValidation(
            ok=ok,
            bar_count=int(report.get("barCount") or report.get("bar_count") or 0),
            start_ts=report.get("startTs") or report.get("start_ts"),
            end_ts=report.get("endTs") or report.get("end_ts"),
            content_hash=content_hash,
            byte_size=int(report.get("byteSize") or byte_size),
            error=report.get("error"),
            columns=tuple(report.get("columns") or REQUIRED_OHLCV_COLUMNS),
            parquet_available=_parquet_available(),
            duplicate_count=int(report.get("duplicateCount") or 0),
        )


def validate_ohlcv_optional_native(
    path: Path | str,
    *,
    prefer_native: bool | None = None,
) -> OhlcvValidation:
    """Validate OHLCV; optionally try native first when enabled.

    ``prefer_native`` defaults from env ``LEVIATHAN_NATIVE_OHLCV=1``.
    MarketSim / RiskGuard continue to use Python ``validate_ohlcv_file`` unless
    callers explicitly opt in via this helper.
    """
    if prefer_native is None:
        prefer_native = os.environ.get("LEVIATHAN_NATIVE_OHLCV", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if prefer_native:
        native = try_native_ohlcv_validate(path)
        if native is not None:
            return native
    return validate_ohlcv_file(Path(path))


__all__ = [
    "try_native_ohlcv_validate",
    "validate_ohlcv_optional_native",
]
