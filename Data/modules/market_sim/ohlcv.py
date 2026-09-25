"""OHLCV file loading and validation (CSV primary; Parquet optional)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.hashing import sha256_file

from .types import Bar, MarketSimError


REQUIRED_OHLCV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
ALT_TS_COLUMNS = ("timestamp", "ts", "time", "datetime", "date")


@dataclass(frozen=True)
class OhlcvValidation:
    ok: bool
    bar_count: int
    start_ts: str | None
    end_ts: str | None
    content_hash: str
    byte_size: int
    error: str | None = None
    columns: tuple[str, ...] = ()
    parquet_available: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "bar_count": self.bar_count,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
            "error": self.error,
            "columns": list(self.columns),
            "parquet_available": self.parquet_available,
        }


def _normalize_ts(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    # Compact calendar date YYYYMMDD (must precede numeric-epoch handling).
    if len(text) == 8 and text.isdigit():
        dt = datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")
    # Compact datetime YYYYMMDDHHMMSS
    if len(text) == 14 and text.isdigit():
        dt = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")
    # Numeric epoch (seconds, ms, or microseconds)
    if text.replace(".", "", 1).isdigit():
        value = float(text)
        # Microseconds since epoch (~16 digits for modern dates)
        if value >= 1e15:
            value /= 1_000_000.0
        elif value >= 1e12:  # milliseconds
            value /= 1000.0
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
        return dt.isoformat(timespec="seconds")
    # ISO-ish
    cleaned = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unrecognized timestamp: {text!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _map_header(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise MarketSimError("INVALID_OHLCV", "CSV has no header row")
    lower = {name.strip().lower(): name for name in fieldnames if name}
    mapping: dict[str, str] = {}
    for alt in ALT_TS_COLUMNS:
        if alt in lower:
            mapping["timestamp"] = lower[alt]
            break
    for col in ("open", "high", "low", "close", "volume"):
        if col in lower:
            mapping[col] = lower[col]
        elif col == "volume" and "vol" in lower:
            mapping[col] = lower["vol"]
    missing = [c for c in REQUIRED_OHLCV_COLUMNS if c not in mapping]
    if missing:
        raise MarketSimError(
            "INVALID_OHLCV",
            f"Missing columns: {missing}; found={sorted(lower)}",
        )
    return mapping


def iter_ohlcv_csv(path: Path) -> Iterator[Bar]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        mapping = _map_header(list(reader.fieldnames or []))
        prev_ts: str | None = None
        for row_num, row in enumerate(reader, start=2):
            try:
                ts = _normalize_ts(str(row[mapping["timestamp"]]))
                o = float(row[mapping["open"]])
                h = float(row[mapping["high"]])
                l = float(row[mapping["low"]])
                c = float(row[mapping["close"]])
                v = float(row[mapping["volume"]])
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketSimError(
                    "INVALID_OHLCV",
                    f"Row {row_num}: {exc}",
                ) from exc
            if h < max(o, c) or l > min(o, c) or h < l:
                raise MarketSimError(
                    "INVALID_OHLCV",
                    f"Row {row_num}: OHLC inconsistency o={o} h={h} l={l} c={c}",
                )
            if prev_ts is not None and ts < prev_ts:
                raise MarketSimError(
                    "INVALID_OHLCV",
                    f"Row {row_num}: timestamps not sorted ({prev_ts} -> {ts})",
                )
            if prev_ts is not None and ts == prev_ts:
                raise MarketSimError(
                    "INVALID_OHLCV",
                    f"Row {row_num}: duplicate timestamp {ts}",
                )
            prev_ts = ts
            yield Bar(ts=ts, open=o, high=h, low=l, close=c, volume=v)


def _parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def load_ohlcv(path: Path, *, start_ts: str | None = None, end_ts: str | None = None) -> list[Bar]:
    path = Path(path)
    if not path.is_file():
        raise MarketSimError("DATA_NOT_FOUND", f"Market file not found: {path}", http_status=404)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        if not _parquet_available():
            raise MarketSimError(
                "PARQUET_UNAVAILABLE",
                "Parquet support requires optional dependency pyarrow (not installed)",
                http_status=503,
            )
        bars = _load_parquet(path)
    elif suffix in {".csv", ".txt"}:
        bars = list(iter_ohlcv_csv(path))
    else:
        raise MarketSimError("UNSUPPORTED_FORMAT", f"Unsupported market file format: {suffix}")

    if start_ts:
        bars = [b for b in bars if b.ts >= start_ts]
    if end_ts:
        bars = [b for b in bars if b.ts <= end_ts]
    if not bars:
        raise MarketSimError("EMPTY_WINDOW", "No bars in requested date range")
    return bars


def _load_parquet(path: Path) -> list[Bar]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    cols = {name.lower(): name for name in table.column_names}
    mapping: dict[str, str] = {}
    for alt in ALT_TS_COLUMNS:
        if alt in cols:
            mapping["timestamp"] = cols[alt]
            break
    for col in ("open", "high", "low", "close", "volume"):
        if col in cols:
            mapping[col] = cols[col]
    missing = [c for c in REQUIRED_OHLCV_COLUMNS if c not in mapping]
    if missing:
        raise MarketSimError("INVALID_OHLCV", f"Parquet missing columns: {missing}")

    ts_col = table.column(mapping["timestamp"]).to_pylist()
    o_col = table.column(mapping["open"]).to_pylist()
    h_col = table.column(mapping["high"]).to_pylist()
    l_col = table.column(mapping["low"]).to_pylist()
    c_col = table.column(mapping["close"]).to_pylist()
    v_col = table.column(mapping["volume"]).to_pylist()
    bars: list[Bar] = []
    prev: str | None = None
    for i, raw_ts in enumerate(ts_col):
        ts = _normalize_ts(str(raw_ts))
        if prev is not None and ts < prev:
            raise MarketSimError("INVALID_OHLCV", f"Parquet row {i}: unsorted timestamps")
        if prev is not None and ts == prev:
            raise MarketSimError("INVALID_OHLCV", f"Parquet row {i}: duplicate timestamp {ts}")
        prev = ts
        bars.append(
            Bar(
                ts=ts,
                open=float(o_col[i]),
                high=float(h_col[i]),
                low=float(l_col[i]),
                close=float(c_col[i]),
                volume=float(v_col[i]),
            )
        )
    return bars


def validate_ohlcv_file(path: Path) -> OhlcvValidation:
    path = Path(path)
    parquet_ok = _parquet_available()
    if not path.is_file():
        return OhlcvValidation(
            ok=False,
            bar_count=0,
            start_ts=None,
            end_ts=None,
            content_hash="",
            byte_size=0,
            error="file not found",
            parquet_available=parquet_ok,
        )
    byte_size = path.stat().st_size
    try:
        content_hash = sha256_file(path)
        bars = load_ohlcv(path)
        return OhlcvValidation(
            ok=True,
            bar_count=len(bars),
            start_ts=bars[0].ts,
            end_ts=bars[-1].ts,
            content_hash=content_hash,
            byte_size=byte_size,
            columns=REQUIRED_OHLCV_COLUMNS,
            parquet_available=parquet_ok,
        )
    except MarketSimError as exc:
        try:
            content_hash = sha256_file(path)
        except OSError:
            content_hash = ""
        return OhlcvValidation(
            ok=False,
            bar_count=0,
            start_ts=None,
            end_ts=None,
            content_hash=content_hash,
            byte_size=byte_size,
            error=exc.message,
            parquet_available=parquet_ok,
        )


def infer_symbol_timeframe(path: Path) -> tuple[str, str]:
    """Best-effort parse from filename like BTCUSDT_1h.csv or btc-1h.csv."""
    stem = path.stem
    parts = stem.replace("-", "_").split("_")
    symbol = parts[0].upper() if parts else "UNKNOWN"
    timeframe = "1h"
    candidates = {"1m", "5m", "15m", "1h", "4h", "1d", "1D", "d1", "D1"}
    for part in parts[1:]:
        if part in candidates or part.lower() in {c.lower() for c in candidates}:
            timeframe = "1D" if part.lower() in {"1d", "d1"} else part
            break
    return symbol, timeframe


_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1D": 86400,
    "1d": 86400,
    "d1": 86400,
    "D1": 86400,
}


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def analyze_ohlcv_quality(
    path: Path,
    *,
    timezone: str = "UTC",
    adjustment_mode: str = "unspecified",
    expected_timeframe: str | None = None,
    outlier_return_pct: float = 35.0,
) -> dict[str, Any]:
    """Quality analysis for the import pipeline — never silently repairs data."""
    path = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    operations: list[dict[str, Any]] = [
        {
            "op": "analyze_ohlcv_quality",
            "path": str(path),
            "silent_repair": False,
            "timezone": timezone,
            "adjustment_mode": adjustment_mode,
        }
    ]
    if not path.is_file():
        return {
            "schema_ok": False,
            "errors": ["file not found"],
            "warnings": warnings,
            "operations": operations,
            "duplicate_timestamps": 0,
            "unordered_pairs": 0,
            "known_gaps": [],
            "outlier_bars": [],
            "timezone": timezone,
            "adjustment_mode": adjustment_mode,
        }

    # Re-scan raw CSV for duplicate/order stats even when load fails.
    duplicate_timestamps = 0
    unordered_pairs = 0
    known_gaps: list[dict[str, Any]] = []
    outlier_bars: list[dict[str, Any]] = []
    schema_ok = True
    bars: list[Bar] = []
    try:
        bars = load_ohlcv(path)
    except MarketSimError as exc:
        schema_ok = False
        errors.append(exc.message)
        # Best-effort gap/dupe scan via raw CSV when possible.
        if path.suffix.lower() in {".csv", ".txt"}:
            try:
                raw_ts: list[str] = []
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    mapping = _map_header(list(reader.fieldnames or []))
                    for row in reader:
                        try:
                            raw_ts.append(_normalize_ts(str(row[mapping["timestamp"]])))
                        except (KeyError, TypeError, ValueError):
                            continue
                for i in range(1, len(raw_ts)):
                    if raw_ts[i] == raw_ts[i - 1]:
                        duplicate_timestamps += 1
                    elif raw_ts[i] < raw_ts[i - 1]:
                        unordered_pairs += 1
            except MarketSimError:
                pass
        return {
            "schema_ok": schema_ok,
            "errors": errors,
            "warnings": warnings,
            "operations": operations,
            "duplicate_timestamps": duplicate_timestamps,
            "unordered_pairs": unordered_pairs,
            "known_gaps": known_gaps,
            "outlier_bars": outlier_bars,
            "timezone": timezone,
            "adjustment_mode": adjustment_mode,
        }

    # Loaded successfully — still scan for gaps / outliers (duplicates already rejected).
    tf = expected_timeframe
    if tf is None:
        _, tf = infer_symbol_timeframe(path)
    step = _TIMEFRAME_SECONDS.get(str(tf), None)
    if step and len(bars) >= 2:
        for i in range(1, len(bars)):
            prev = _parse_iso(bars[i - 1].ts)
            cur = _parse_iso(bars[i].ts)
            delta = int((cur - prev).total_seconds())
            if delta > step * 1.5:
                missing = max(0, int(round(delta / step)) - 1)
                known_gaps.append(
                    {
                        "after_ts": bars[i - 1].ts,
                        "before_ts": bars[i].ts,
                        "expected_step_seconds": step,
                        "actual_delta_seconds": delta,
                        "estimated_missing_bars": missing,
                    }
                )
    if known_gaps:
        warnings.append(f"{len(known_gaps)} gap(s) detected; recorded, not repaired")

    for i in range(1, len(bars)):
        prev_c = bars[i - 1].close
        if prev_c == 0:
            continue
        ret_pct = abs((bars[i].close - prev_c) / prev_c) * 100.0
        if ret_pct >= outlier_return_pct:
            outlier_bars.append(
                {
                    "ts": bars[i].ts,
                    "return_pct": round(ret_pct, 4),
                    "prev_close": prev_c,
                    "close": bars[i].close,
                }
            )
    if outlier_bars:
        warnings.append(f"{len(outlier_bars)} outlier bar(s) flagged; not repaired")

    if timezone.upper() != "UTC":
        warnings.append(
            f"timezone={timezone} recorded; bars are normalized to UTC on ingest"
        )
        operations.append(
            {
                "op": "timezone_normalization",
                "declared": timezone,
                "stored_as": "UTC",
                "silent_repair": False,
            }
        )

    return {
        "schema_ok": True,
        "errors": errors,
        "warnings": warnings,
        "operations": operations,
        "duplicate_timestamps": 0,
        "unordered_pairs": 0,
        "known_gaps": known_gaps,
        "outlier_bars": outlier_bars,
        "timezone": timezone,
        "adjustment_mode": adjustment_mode,
        "bar_count": len(bars),
        "start_ts": bars[0].ts if bars else None,
        "end_ts": bars[-1].ts if bars else None,
    }
