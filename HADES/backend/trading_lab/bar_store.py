"""Partitioned bulk market history.

Design decision (see docs/TRADING_LAB.md): HADES stays offline-first and Windows-first, and
``pyarrow`` is a large native dependency that is not in ``backend/requirements.txt``. Instead
of forcing it, bulk history is stored as **partitioned fixed-width binary records** —
one partition file per (instrument, timeframe, year):

- records are 108 bytes, little-endian, and written in event-time order;
- because the record width is fixed and the file is sorted, a point-in-time lookup is a
  binary search with two seeks instead of a full scan;
- reads are chunked generators, so a 25-year multi-instrument dataset is never fully
  resident in RAM;
- SQLite keeps only metadata (manifests, coverage, checksums), which is what it is good at.

``export_parquet`` is available when ``pyarrow`` happens to be installed, for users who want
to analyse the same partitions in an external tool. It is never required.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
from bisect import bisect_left
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from trading_lab.contracts import MarketEvent, utc_iso

RECORD_FORMAT = "<qq11dI"
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)
_PACKER = struct.Struct(RECORD_FORMAT)
PARTITION_SUFFIX = ".hbars"
DEFAULT_CHUNK_RECORDS = 4096

assert RECORD_SIZE == 108, f"unexpected record size {RECORD_SIZE}"


def _nan_to_none(value: float) -> float | None:
    return None if math.isnan(value) else value


def _none_to_nan(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def safe_component(value: str) -> str:
    out = []
    for char in value:
        out.append(char if char.isalnum() or char in "-._" else "_")
    return "".join(out) or "unknown"


class BarPartitionStore:
    """Filesystem owner of bulk market history."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- layout ------------------------------------------------------------------

    def series_dir(self, instrument_id: str, timeframe: str) -> Path:
        return self.root / safe_component(instrument_id) / safe_component(timeframe)

    def partition_path(self, instrument_id: str, timeframe: str, year: int) -> Path:
        return self.series_dir(instrument_id, timeframe) / f"{year:04d}{PARTITION_SUFFIX}"

    def partitions(self, instrument_id: str, timeframe: str) -> list[Path]:
        directory = self.series_dir(instrument_id, timeframe)
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob(f"*{PARTITION_SUFFIX}") if path.is_file())

    def partition_names(self, instrument_id: str, timeframe: str) -> list[str]:
        base = self.root
        return [str(path.relative_to(base)).replace("\\", "/") for path in self.partitions(instrument_id, timeframe)]

    # --- writing -----------------------------------------------------------------

    def write(
        self,
        instrument_id: str,
        timeframe: str,
        events: Sequence[MarketEvent],
        *,
        replace: bool = True,
    ) -> dict[str, object]:
        """Write events into year partitions.

        ``replace=True`` rewrites only the partitions the payload touches, so importing 2019
        does not destroy 2018. Within a partition, later writes of the same event_time win,
        and the partition is always left sorted and de-duplicated.
        """
        if not events:
            raise ValueError("no_events_to_write")
        directory = self.series_dir(instrument_id, timeframe)
        directory.mkdir(parents=True, exist_ok=True)
        grouped: dict[int, list[MarketEvent]] = {}
        for event in events:
            year = datetime.fromisoformat(event.event_time).astimezone(UTC).year
            grouped.setdefault(year, []).append(event)

        written = 0
        for year, chunk in sorted(grouped.items()):
            path = self.partition_path(instrument_id, timeframe, year)
            merged: dict[int, tuple] = {}
            if path.exists() and not replace:
                for record in self._iter_records(path):
                    merged[record[0]] = record
            elif path.exists() and replace:
                merged = {}
            for event in chunk:
                record = self._to_record(event)
                merged[record[0]] = record
            payload = b"".join(_PACKER.pack(*merged[key]) for key in sorted(merged))
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(payload)
            os.replace(tmp, path)
            written += len(chunk)

        return {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "events_written": written,
            "partitions": self.partition_names(instrument_id, timeframe),
            "checksum": self.checksum(instrument_id, timeframe),
            "row_count": self.count(instrument_id, timeframe),
        }

    def delete_series(self, instrument_id: str, timeframe: str) -> int:
        removed = 0
        for path in self.partitions(instrument_id, timeframe):
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    # --- reading -----------------------------------------------------------------

    def count(self, instrument_id: str, timeframe: str) -> int:
        total = 0
        for path in self.partitions(instrument_id, timeframe):
            total += path.stat().st_size // RECORD_SIZE
        return total

    def coverage(self, instrument_id: str, timeframe: str) -> dict[str, object]:
        paths = self.partitions(instrument_id, timeframe)
        if not paths:
            return {"row_count": 0, "first_event_time": None, "last_event_time": None, "years": []}
        first = self._record_at(paths[0], 0)
        last_path = paths[-1]
        last_index = (last_path.stat().st_size // RECORD_SIZE) - 1
        last = self._record_at(last_path, max(0, last_index))
        return {
            "row_count": self.count(instrument_id, timeframe),
            "first_event_time": utc_iso(datetime.fromtimestamp(first[0], tz=UTC)) if first else None,
            "last_event_time": utc_iso(datetime.fromtimestamp(last[0], tz=UTC)) if last else None,
            "years": [path.stem for path in paths],
            "partitions": self.partition_names(instrument_id, timeframe),
        }

    def iter_events(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        start: str | None = None,
        end: str | None = None,
        available_until: str | None = None,
        chunk_records: int = DEFAULT_CHUNK_RECORDS,
    ) -> Iterator[MarketEvent]:
        """Stream events in chronological order without loading the whole series."""
        start_ts = _epoch(start) if start else None
        end_ts = _epoch(end) if end else None
        available_ts = _epoch(available_until) if available_until else None
        for path in self.partitions(instrument_id, timeframe):
            total = path.stat().st_size // RECORD_SIZE
            if total == 0:
                continue
            offset = 0
            if start_ts is not None:
                offset = self._search(path, start_ts)
                if offset >= total:
                    continue
            with path.open("rb") as handle:
                handle.seek(offset * RECORD_SIZE)
                while True:
                    blob = handle.read(RECORD_SIZE * max(1, chunk_records))
                    if not blob:
                        break
                    for index in range(0, len(blob) - RECORD_SIZE + 1, RECORD_SIZE):
                        record = _PACKER.unpack_from(blob, index)
                        if start_ts is not None and record[0] < start_ts:
                            continue
                        if end_ts is not None and record[0] > end_ts:
                            return
                        if available_ts is not None and record[1] > available_ts:
                            continue
                        yield self._from_record(instrument_id, timeframe, record)

    def read_window(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        available_until: str,
        lookback: int,
    ) -> list[MarketEvent]:
        """Last ``lookback`` events whose ``available_at <= available_until``.

        Reads backwards from the binary-search position, so a lookback of 200 on a 25-year
        series touches a few kilobytes rather than the whole dataset.
        """
        if lookback <= 0:
            return []
        cutoff = _epoch(available_until)
        collected: list[MarketEvent] = []
        for path in reversed(self.partitions(instrument_id, timeframe)):
            total = path.stat().st_size // RECORD_SIZE
            if total == 0:
                continue
            index = min(total, self._search(path, cutoff + 1)) - 1
            while index >= 0 and len(collected) < lookback:
                record = self._record_at(path, index)
                index -= 1
                if record is None:
                    break
                if record[1] > cutoff:
                    continue
                collected.append(self._from_record(instrument_id, timeframe, record))
            if len(collected) >= lookback:
                break
        collected.reverse()
        return collected

    def checksum(self, instrument_id: str, timeframe: str) -> str:
        digest = hashlib.sha256()
        for path in self.partitions(instrument_id, timeframe):
            digest.update(path.name.encode("utf-8"))
            with path.open("rb") as handle:
                while True:
                    blob = handle.read(1 << 20)
                    if not blob:
                        break
                    digest.update(blob)
        return digest.hexdigest()

    # --- optional parquet --------------------------------------------------------

    def export_parquet(self, instrument_id: str, timeframe: str, destination: str | os.PathLike[str]) -> dict[str, object]:
        """Optional convenience export. Requires pyarrow; never required by HADES."""
        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "parquet_export_unavailable: pyarrow is not installed. Trading Lab stores bulk "
                "history in its own partitioned binary format precisely so this dependency stays optional."
            ) from exc
        columns: dict[str, list] = {
            "event_time": [],
            "available_at": [],
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "volume": [],
        }
        rows = 0
        for event in self.iter_events(instrument_id, timeframe):
            columns["event_time"].append(event.event_time)
            columns["available_at"].append(event.available_at)
            columns["open"].append(event.open)
            columns["high"].append(event.high)
            columns["low"].append(event.low)
            columns["close"].append(event.close)
            columns["volume"].append(event.volume)
            rows += 1
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(columns), target)
        return {"path": str(target), "rows": rows}

    # --- record plumbing ---------------------------------------------------------

    @staticmethod
    def _to_record(event: MarketEvent) -> tuple:
        return (
            _epoch(event.event_time),
            _epoch(event.available_at),
            _none_to_nan(event.open),
            _none_to_nan(event.high),
            _none_to_nan(event.low),
            _none_to_nan(event.close),
            float(event.volume or 0.0),
            _none_to_nan(event.bid),
            _none_to_nan(event.ask),
            _none_to_nan(event.mark_price),
            _none_to_nan(event.index_price),
            _none_to_nan(event.funding_rate),
            _none_to_nan(event.open_interest),
            int(max(1, event.revision)),
        )

    @staticmethod
    def _from_record(instrument_id: str, timeframe: str, record: tuple) -> MarketEvent:
        return MarketEvent(
            instrument_id=instrument_id,
            timeframe=timeframe,
            event_time=utc_iso(datetime.fromtimestamp(record[0], tz=UTC)),
            available_at=utc_iso(datetime.fromtimestamp(record[1], tz=UTC)),
            kind="bar",
            open=_nan_to_none(record[2]),
            high=_nan_to_none(record[3]),
            low=_nan_to_none(record[4]),
            close=_nan_to_none(record[5]),
            volume=record[6],
            bid=_nan_to_none(record[7]),
            ask=_nan_to_none(record[8]),
            mark_price=_nan_to_none(record[9]),
            index_price=_nan_to_none(record[10]),
            funding_rate=_nan_to_none(record[11]),
            open_interest=_nan_to_none(record[12]),
            revision=int(record[13]),
            source="partition",
        )

    @staticmethod
    def _iter_records(path: Path) -> Iterator[tuple]:
        with path.open("rb") as handle:
            while True:
                blob = handle.read(RECORD_SIZE * DEFAULT_CHUNK_RECORDS)
                if not blob:
                    return
                for index in range(0, len(blob) - RECORD_SIZE + 1, RECORD_SIZE):
                    yield _PACKER.unpack_from(blob, index)

    @staticmethod
    def _record_at(path: Path, index: int) -> tuple | None:
        size = path.stat().st_size
        total = size // RECORD_SIZE
        if index < 0 or index >= total:
            return None
        with path.open("rb") as handle:
            handle.seek(index * RECORD_SIZE)
            blob = handle.read(RECORD_SIZE)
        if len(blob) < RECORD_SIZE:
            return None
        return _PACKER.unpack(blob)

    @classmethod
    def _search(cls, path: Path, target_ts: int) -> int:
        """Index of the first record with ``event_time >= target_ts`` (binary search)."""
        total = path.stat().st_size // RECORD_SIZE
        if total == 0:
            return 0
        low, high = 0, total
        with path.open("rb") as handle:
            while low < high:
                mid = (low + high) // 2
                handle.seek(mid * RECORD_SIZE)
                blob = handle.read(8)
                if len(blob) < 8:
                    break
                (event_ts,) = struct.unpack("<q", blob)
                if event_ts < target_ts:
                    low = mid + 1
                else:
                    high = mid
        return low


class InMemoryEventSeries:
    """Small helper for auxiliary series (corporate actions, funding, events, news).

    These series are sparse by nature; a partition file per year would be wasteful. They are
    kept sorted in memory per dataset and looked up with ``bisect``.
    """

    def __init__(self, events: Iterable[MarketEvent] | None = None) -> None:
        self._events: list[MarketEvent] = sorted(events or [], key=lambda item: item.available_at)
        self._keys = [item.available_at for item in self._events]

    def add(self, event: MarketEvent) -> None:
        position = bisect_left(self._keys, event.available_at)
        self._events.insert(position, event)
        self._keys.insert(position, event.available_at)

    def available_until(self, moment: str) -> list[MarketEvent]:
        cut = bisect_left(self._keys, moment)
        if cut < len(self._keys) and self._keys[cut] == moment:
            cut += 1
        return self._events[:cut]

    def between(self, start: str, end: str) -> list[MarketEvent]:
        return [event for event in self._events if start < event.available_at <= end]

    def __len__(self) -> int:
        return len(self._events)


__all__ = [
    "BarPartitionStore",
    "DEFAULT_CHUNK_RECORDS",
    "InMemoryEventSeries",
    "RECORD_SIZE",
    "safe_component",
]
