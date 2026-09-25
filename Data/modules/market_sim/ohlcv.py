"""OHLCV file loading and validation (CSV primary; Parquet optional)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator  # Any used by parquet column helpers

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
    duplicate_count: int = 0
    gap_count: int = 0
    quality: dict[str, Any] | None = None

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
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "quality": self.quality,
        }


def _normalize_ts(raw: str) -> str:
    """Normalize vendor timestamps to UTC ISO-8601 seconds.

    Handles ISO, common calendar formats, ``YYYYMMDD``, and epoch seconds /
    milliseconds / microseconds. Digits that look like calendar dates are
    never treated as Unix epochs.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty timestamp")

    # Compact calendar date YYYYMMDD (and optional HHMMSS) — before epoch heuristics.
    if text.isdigit() and len(text) == 8:
        dt = datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")
    if text.isdigit() and len(text) == 14:
        dt = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")

    # Numeric epoch (seconds / ms / µs)
    if text.replace(".", "", 1).isdigit():
        value = float(text)
        # Microseconds since epoch (~1e15 for 2024)
        if value >= 1e14:
            value /= 1_000_000.0
        elif value >= 1e12:  # milliseconds
            value /= 1000.0
        # Values that look like YYYYMMDD after float parse (e.g. 20240115.0)
        if 19_000_000 <= value <= 21_001_231 and value == int(value):
            as_int = int(value)
            as_text = f"{as_int:08d}"
            if len(as_text) == 8:
                dt = datetime.strptime(as_text, "%Y%m%d").replace(tzinfo=timezone.utc)
                return dt.isoformat(timespec="seconds")
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
        return dt.isoformat(timespec="seconds")

    # ISO-ish
    cleaned = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
            "%Y%m%d",
            "%Y%m%d%H%M%S",
        ):
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


def iter_ohlcv_csv(
    path: Path,
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> Iterator[Bar]:
    """Stream CSV bars without materializing the full series."""
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
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                break
            yield Bar(ts=ts, open=o, high=h, low=l, close=c, volume=v)


def _parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def iter_ohlcv(
    path: Path | str,
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> Iterator[Bar]:
    """Canonical streaming OHLCV reader — does not materialize the full series.

    Prefer this over ``load_ohlcv`` for ingest, validation, split-manifest
    construction, and any path that must stay within a memory budget.
    """
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
        yield from _iter_parquet(path, start_ts=start_ts, end_ts=end_ts)
    elif suffix in {".csv", ".txt"}:
        yield from iter_ohlcv_csv(path, start_ts=start_ts, end_ts=end_ts)
    else:
        raise MarketSimError("UNSUPPORTED_FORMAT", f"Unsupported market file format: {suffix}")


def stream_ohlcv(
    path: Path | str,
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> Iterator[Bar]:
    """Alias for ``iter_ohlcv`` (characterization / Master Program P1A surface)."""
    yield from iter_ohlcv(path, start_ts=start_ts, end_ts=end_ts)


def load_ohlcv(path: Path, *, start_ts: str | None = None, end_ts: str | None = None) -> list[Bar]:
    """Materialize bars for small fixtures / SimulationClock. Prefer ``iter_ohlcv``."""
    bars = list(iter_ohlcv(path, start_ts=start_ts, end_ts=end_ts))
    if not bars:
        raise MarketSimError("EMPTY_WINDOW", "No bars in requested date range")
    return bars


def _iter_parquet(
    path: Path,
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> Iterator[Bar]:
    """Stream parquet by row-group / batch — avoids loading the whole table."""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    cols = {name.lower(): name for name in (pf.schema_arrow.names if pf.schema_arrow else [])}
    if not cols:
        # Fallback for older pyarrow: read schema from first batch
        table = pq.read_table(path)
        cols = {name.lower(): name for name in table.column_names}
        mapping = _parquet_column_map(cols)
        yield from _bars_from_column_lists(
            table.column(mapping["timestamp"]).to_pylist(),
            table.column(mapping["open"]).to_pylist(),
            table.column(mapping["high"]).to_pylist(),
            table.column(mapping["low"]).to_pylist(),
            table.column(mapping["close"]).to_pylist(),
            table.column(mapping["volume"]).to_pylist(),
            start_ts=start_ts,
            end_ts=end_ts,
        )
        return

    mapping = _parquet_column_map(cols)
    needed = [mapping[c] for c in REQUIRED_OHLCV_COLUMNS]
    prev: str | None = None
    row_offset = 0
    for batch in pf.iter_batches(columns=needed, batch_size=65_536):
        ts_col = batch.column(needed.index(mapping["timestamp"])).to_pylist()
        o_col = batch.column(needed.index(mapping["open"])).to_pylist()
        h_col = batch.column(needed.index(mapping["high"])).to_pylist()
        l_col = batch.column(needed.index(mapping["low"])).to_pylist()
        c_col = batch.column(needed.index(mapping["close"])).to_pylist()
        v_col = batch.column(needed.index(mapping["volume"])).to_pylist()
        for i, raw_ts in enumerate(ts_col):
            ts = _normalize_ts(str(raw_ts))
            if prev is not None and ts < prev:
                raise MarketSimError(
                    "INVALID_OHLCV",
                    f"Parquet row {row_offset + i}: unsorted timestamps",
                )
            if prev is not None and ts == prev:
                raise MarketSimError(
                    "INVALID_OHLCV",
                    f"Parquet row {row_offset + i}: duplicate timestamp {ts}",
                )
            prev = ts
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                return
            yield Bar(
                ts=ts,
                open=float(o_col[i]),
                high=float(h_col[i]),
                low=float(l_col[i]),
                close=float(c_col[i]),
                volume=float(v_col[i]),
            )
        row_offset += len(ts_col)


def _parquet_column_map(cols: dict[str, str]) -> dict[str, str]:
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
    return mapping


def _bars_from_column_lists(
    ts_col: list[Any],
    o_col: list[Any],
    h_col: list[Any],
    l_col: list[Any],
    c_col: list[Any],
    v_col: list[Any],
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> Iterator[Bar]:
    prev: str | None = None
    for i, raw_ts in enumerate(ts_col):
        ts = _normalize_ts(str(raw_ts))
        if prev is not None and ts < prev:
            raise MarketSimError("INVALID_OHLCV", f"Parquet row {i}: unsorted timestamps")
        if prev is not None and ts == prev:
            raise MarketSimError("INVALID_OHLCV", f"Parquet row {i}: duplicate timestamp {ts}")
        prev = ts
        if start_ts and ts < start_ts:
            continue
        if end_ts and ts > end_ts:
            break
        yield Bar(
            ts=ts,
            open=float(o_col[i]),
            high=float(h_col[i]),
            low=float(l_col[i]),
            close=float(c_col[i]),
            volume=float(v_col[i]),
        )


def count_ohlcv(
    path: Path | str,
    *,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> int:
    """Count bars via streaming — O(1) extra memory beyond one bar."""
    return sum(1 for _ in iter_ohlcv(path, start_ts=start_ts, end_ts=end_ts))


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
        gap_count = 0
        if len(bars) >= 2:
            # Lightweight gap count only — full quality report lives in dataset_pipeline.
            prev_dt = datetime.fromisoformat(bars[0].ts.replace("Z", "+00:00"))
            for bar in bars[1:]:
                cur_dt = datetime.fromisoformat(bar.ts.replace("Z", "+00:00"))
                if (cur_dt - prev_dt).total_seconds() > 86400 * 3:
                    gap_count += 1
                prev_dt = cur_dt
        return OhlcvValidation(
            ok=True,
            bar_count=len(bars),
            start_ts=bars[0].ts,
            end_ts=bars[-1].ts,
            content_hash=content_hash,
            byte_size=byte_size,
            columns=REQUIRED_OHLCV_COLUMNS,
            parquet_available=parquet_ok,
            duplicate_count=0,
            gap_count=gap_count,
            quality={"gap_count": gap_count} if gap_count else None,
        )
    except MarketSimError as exc:
        try:
            content_hash = sha256_file(path)
        except OSError:
            content_hash = ""
        dup = 1 if "duplicate timestamp" in (exc.message or "") else 0
        return OhlcvValidation(
            ok=False,
            bar_count=0,
            start_ts=None,
            end_ts=None,
            content_hash=content_hash,
            byte_size=byte_size,
            error=exc.message,
            parquet_available=parquet_ok,
            duplicate_count=dup,
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
