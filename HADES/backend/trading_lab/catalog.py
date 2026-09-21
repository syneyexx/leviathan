"""Market Data Catalog.

Owns the path from raw rows to an immutable, versioned dataset:

    provider rows -> BarValidator -> BarPartitionStore -> DatasetManifest -> SQLite metadata

Three properties matter and are enforced rather than documented:

- **Immutability.** A frozen dataset is never overwritten. Re-importing the same instrument
  and timeframe creates a new revision with its own checksum, so an experiment that names a
  dataset revision can always be reproduced.
- **Three timestamps.** Every event carries the moment it describes (``event_time``), the
  moment the information could have been acted on (``available_at``) and the moment it
  entered HADES (``ingested_at``). Only ``available_at`` gates the simulation.
- **Chronological splits.** Development, validation and sealed test are contiguous windows in
  time, never shuffled. The split boundaries live on the dataset so every consumer sees the
  same ones.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Sequence

from trading_lab.bar_store import BarPartitionStore
from trading_lab.calendars import get_calendar, timeframe_seconds
from trading_lab.contracts import (
    DataLevel,
    DatasetManifest,
    InstrumentSpec,
    SplitName,
    stable_hash,
    utc_iso,
)
from trading_lab.data_quality import BarValidator, normalise_timestamp
from trading_lab.providers import ProviderError, build_provider

SPLIT_ORDER: tuple[SplitName, ...] = ("development", "validation", "sealed_test")


@dataclass(frozen=True)
class SplitWindow:
    name: SplitName
    start: str
    end: str

    def contains(self, moment: str) -> bool:
        return self.start <= moment < self.end

    def as_json(self) -> dict[str, str]:
        return {"name": self.name, "start": self.start, "end": self.end}


def chronological_splits(
    first_event_time: str,
    last_event_time: str,
    *,
    development: float = 0.6,
    validation: float = 0.2,
    embargo_seconds: int = 0,
) -> list[SplitWindow]:
    """Contiguous time windows, in order, with an optional embargo gap between them.

    The embargo exists because a strategy or model whose features span N observations sees
    into the next window at the boundary. Cutting a gap out of the timeline is cheap and
    removes the leak.
    """
    start = normalise_timestamp(first_event_time)
    end = normalise_timestamp(last_event_time)
    if end <= start:
        raise ValueError("last_event_time_must_be_after_first_event_time")
    total = (end - start).total_seconds()
    development = max(0.1, min(0.9, development))
    validation = max(0.05, min(0.9 - development, validation))
    development_end = start + timedelta(seconds=total * development)
    validation_start = development_end + timedelta(seconds=embargo_seconds)
    validation_end = validation_start + timedelta(seconds=total * validation)
    test_start = validation_end + timedelta(seconds=embargo_seconds)
    if test_start >= end:
        test_start = validation_end
    return [
        SplitWindow("development", utc_iso(start), utc_iso(development_end)),
        SplitWindow("validation", utc_iso(validation_start), utc_iso(validation_end)),
        SplitWindow("sealed_test", utc_iso(test_start), utc_iso(end + timedelta(seconds=1))),
    ]


def walk_forward_folds(
    first_event_time: str,
    last_event_time: str,
    *,
    folds: int = 4,
    scheme: str = "expanding",
    embargo_seconds: int = 0,
) -> list[dict[str, str]]:
    """Chronological train/test folds. ``expanding`` grows the training window each fold."""
    start = normalise_timestamp(first_event_time)
    end = normalise_timestamp(last_event_time)
    folds = max(2, min(20, folds))
    total = (end - start).total_seconds()
    if total <= 0:
        return []
    block = total / (folds + 1)
    out: list[dict[str, str]] = []
    for index in range(folds):
        train_end = start + timedelta(seconds=block * (index + 1))
        test_start = train_end + timedelta(seconds=embargo_seconds)
        test_end = min(end, test_start + timedelta(seconds=block))
        if test_start >= test_end:
            break
        train_start = start if scheme == "expanding" else train_end - timedelta(seconds=block)
        out.append(
            {
                "fold": str(index + 1),
                "train_start": utc_iso(max(start, train_start)),
                "train_end": utc_iso(train_end),
                "test_start": utc_iso(test_start),
                "test_end": utc_iso(test_end),
            }
        )
    return out


class MarketDataCatalog:
    def __init__(self, store: Any, bar_store: BarPartitionStore, registry: Any) -> None:
        self.store = store
        self.bars = bar_store
        self.registry = registry

    # --- import ------------------------------------------------------------------

    def import_rows(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        rows: Sequence[dict[str, Any]],
        provider: str,
        provider_kind: str = "import",
        name: str = "",
        source_reference: str = "",
        licence: str = "unspecified",
        is_synthetic: bool = False,
        data_level: DataLevel = "ohlcv",
        availability_delay_seconds: int = 0,
        assume_timezone: str = "UTC",
        metadata: dict[str, Any] | None = None,
        replace_existing_revision: bool = False,
    ) -> dict[str, Any]:
        """Validate, store and register one dataset revision."""
        spec: InstrumentSpec = self.registry.get(instrument_id)
        if not rows:
            raise ValueError("no_rows_to_import")
        validator = BarValidator(
            spec,
            timeframe,
            source=provider,
            availability_delay_seconds=availability_delay_seconds,
            assume_timezone=assume_timezone,
        )
        events, quality = validator.validate(rows)
        if not events:
            return {
                "accepted": False,
                "reason": "every row was rejected by validation",
                "quality": quality.model_dump(),
            }

        existing = self._latest_revision(instrument_id, timeframe, data_level)
        revision = 1 if existing is None else int(existing.get("revision", 1)) + 1
        if existing is not None and replace_existing_revision and not existing.get("frozen"):
            revision = int(existing.get("revision", 1))

        write_result = self.bars.write(instrument_id, timeframe, events, replace=True)
        checksum = str(write_result.get("checksum", ""))
        dataset_id = self._dataset_id(instrument_id, timeframe, data_level, revision)
        manifest = DatasetManifest(
            dataset_id=dataset_id,
            name=name or f"{spec.symbol} {timeframe} r{revision}",
            instrument_id=instrument_id,
            timeframe=timeframe,
            data_level=data_level,
            provider=provider,
            provider_kind=provider_kind,  # type: ignore[arg-type]
            source_reference=source_reference,
            licence=licence,
            is_synthetic=is_synthetic,
            revision=revision,
            row_count=int(write_result.get("row_count", len(events))),
            first_event_time=events[0].event_time,
            last_event_time=events[-1].event_time,
            calendar=spec.calendar,
            timezone=spec.timezone,
            availability_delay_seconds=availability_delay_seconds,
            content_checksum=checksum,
            partitions=[str(item) for item in write_result.get("partitions", [])],
            quality=quality,
            frozen=False,
            created_at=utc_iso(datetime.now(tz=UTC)),
            metadata={
                **(metadata or {}),
                "splits": [window.as_json() for window in chronological_splits(events[0].event_time, events[-1].event_time)],
                "import_rows_in": quality.rows_in,
            },
        )
        record = self.store.upsert_dataset(manifest)
        return {
            "accepted": True,
            "dataset": record,
            "quality": quality.model_dump(),
            "events_written": write_result.get("events_written", len(events)),
            "checksum": checksum,
        }

    def import_text(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        text: str,
        provider: str = "csv_import",
        **kwargs: Any,
    ) -> dict[str, Any]:
        parser = build_provider("csv_import")
        rows, parse_meta = parser.parse(text)  # type: ignore[attr-defined]
        result = self.import_rows(
            instrument_id=instrument_id,
            timeframe=timeframe,
            rows=rows,
            provider=provider,
            provider_kind="import",
            metadata={"parse": parse_meta},
            **kwargs,
        )
        result["parse"] = parse_meta
        return result

    def download(
        self,
        *,
        provider_id: str,
        instrument_id: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 5000,
        settings: dict[str, Any] | None = None,
        **provider_kwargs: Any,
    ) -> dict[str, Any]:
        spec: InstrumentSpec = self.registry.get(instrument_id)
        provider = build_provider(provider_id, settings)
        status = provider.status()
        if not status.configured:
            return {
                "accepted": False,
                "reason": "provider_not_configured",
                "provider": status.as_json(),
            }
        try:
            rows, meta = provider.fetch(
                symbol=spec.symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                limit=limit,
                **provider_kwargs,
            )
        except ProviderError as exc:
            return {"accepted": False, "reason": str(exc), "provider": status.as_json()}
        if not rows:
            return {"accepted": False, "reason": "provider_returned_no_rows", "provider": status.as_json()}
        return self.import_rows(
            instrument_id=instrument_id,
            timeframe=timeframe,
            rows=rows,
            provider=provider_id,
            provider_kind=provider.kind,  # type: ignore[arg-type]
            licence=provider.licence,
            is_synthetic=provider.kind == "synthetic",
            source_reference=str(meta),
            metadata={"provider_meta": meta},
        )

    def generate_synthetic(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        start: str,
        end: str,
        seed: int = 20240101,
        regime: str = "mixed",
        start_price: float = 100.0,
        limit: int = 200000,
    ) -> dict[str, Any]:
        spec: InstrumentSpec = self.registry.get(instrument_id)
        provider = build_provider("synthetic")
        rows, meta = provider.fetch(  # type: ignore[call-arg]
            symbol=spec.symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
            seed=seed,
            regime=regime,
            start_price=start_price,
            calendar_id=spec.calendar,
        )
        return self.import_rows(
            instrument_id=instrument_id,
            timeframe=timeframe,
            rows=rows,
            provider="synthetic",
            provider_kind="synthetic",
            licence="generated locally — not market data",
            is_synthetic=True,
            name=f"SYNTHETIC {spec.symbol} {timeframe} {regime}",
            source_reference=f"seed={seed} regime={regime}",
            metadata={"provider_meta": meta},
        )

    # --- lifecycle ---------------------------------------------------------------

    def freeze(self, dataset_id: str) -> dict[str, Any] | None:
        """Freeze a revision. Frozen datasets are the only ones an evaluation may cite."""
        return self.store.freeze_dataset(dataset_id)

    def get(self, dataset_id: str) -> dict[str, Any] | None:
        return self.store.get_dataset(dataset_id)

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        return self.store.list_datasets(**filters)

    def resolve(self, instrument_id: str, timeframe: str, *, revision: int | None = None) -> dict[str, Any] | None:
        candidates = [
            row
            for row in self.store.list_datasets(instrument_id=instrument_id, limit=500)
            if row.get("timeframe") == timeframe
        ]
        if not candidates:
            return None
        if revision is not None:
            for row in candidates:
                if int(row.get("revision", 1)) == revision:
                    return row
            return None
        return max(candidates, key=lambda row: int(row.get("revision", 1)))

    def splits(self, dataset: dict[str, Any]) -> list[SplitWindow]:
        raw = (dataset.get("metadata") or {}).get("splits")
        if raw:
            return [SplitWindow(item["name"], item["start"], item["end"]) for item in raw]
        first, last = dataset.get("first_event_time"), dataset.get("last_event_time")
        if not first or not last:
            return []
        return chronological_splits(first, last)

    def set_splits(
        self,
        dataset_id: str,
        *,
        development: float = 0.6,
        validation: float = 0.2,
        embargo_seconds: int = 0,
    ) -> dict[str, Any] | None:
        dataset = self.store.get_dataset(dataset_id)
        if dataset is None:
            return None
        if dataset.get("frozen"):
            raise ValueError("dataset_frozen: split boundaries cannot move after freezing")
        first, last = dataset.get("first_event_time"), dataset.get("last_event_time")
        if not first or not last:
            raise ValueError("dataset_has_no_time_range")
        windows = chronological_splits(first, last, development=development, validation=validation, embargo_seconds=embargo_seconds)
        manifest = DatasetManifest.model_validate(
            {
                **dataset,
                "metadata": {**(dataset.get("metadata") or {}), "splits": [window.as_json() for window in windows]},
            }
        )
        return self.store.upsert_dataset(manifest)

    def split_of(self, dataset: dict[str, Any], moment: str) -> SplitName:
        for window in self.splits(dataset):
            if window.contains(moment):
                return window.name
        return "development"

    # --- inspection --------------------------------------------------------------

    def coverage(self, instrument_id: str, timeframe: str) -> dict[str, Any]:
        return dict(self.bars.coverage(instrument_id, timeframe))

    def gaps(self, instrument_id: str, timeframe: str, *, limit: int = 50) -> dict[str, Any]:
        """Report missing periods against the instrument's calendar."""
        spec: InstrumentSpec = self.registry.get(instrument_id)
        calendar = get_calendar(spec.calendar)
        step = timeframe_seconds(timeframe)
        previous: datetime | None = None
        gaps: list[dict[str, Any]] = []
        total = 0
        expected = 0
        for event in self.bars.iter_events(instrument_id, timeframe):
            total += 1
            moment = normalise_timestamp(event.event_time)
            if previous is not None:
                delta = (moment - previous).total_seconds()
                if delta > step * 1.5:
                    sessions_missing = calendar.expected_periods(previous, moment, step)
                    if sessions_missing > 1:
                        expected += sessions_missing - 1
                        if len(gaps) < limit:
                            gaps.append(
                                {
                                    "from": utc_iso(previous),
                                    "to": utc_iso(moment),
                                    "missing_periods": sessions_missing - 1,
                                    "seconds": delta,
                                }
                            )
            previous = moment
        return {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "rows": total,
            "missing_periods": expected,
            "gap_ratio": (expected / (total + expected)) if total + expected else 0.0,
            "gaps": gaps,
            "calendar": spec.calendar,
        }

    def preview(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in self.bars.iter_events(instrument_id, timeframe, start=start, end=end):
            out.append(
                {
                    "event_time": event.event_time,
                    "available_at": event.available_at,
                    "open": event.open,
                    "high": event.high,
                    "low": event.low,
                    "close": event.close,
                    "volume": event.volume,
                }
            )
            if len(out) >= limit:
                break
        return out

    def latest_close(self, instrument_id: str, timeframe: str) -> dict[str, Any] | None:
        """Chronologically latest close.

        Named explicitly because the legacy bot used ``MAX(close)``, which returns the highest
        price in the series rather than the most recent one.
        """
        coverage = self.bars.coverage(instrument_id, timeframe)
        last = coverage.get("last_event_time")
        if not last:
            return None
        events = self.bars.read_window(instrument_id, timeframe, available_until=str(last), lookback=1)
        if not events:
            return None
        event = events[-1]
        return {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "event_time": event.event_time,
            "close": event.close,
            "volume": event.volume,
        }

    # --- auxiliary event series --------------------------------------------------

    def add_corporate_actions(self, dataset_id: str, actions: Iterable[dict[str, Any]]) -> int:
        dataset = self.store.get_dataset(dataset_id)
        if dataset is None:
            raise ValueError(f"unknown_dataset:{dataset_id}")
        if dataset.get("frozen"):
            raise ValueError("dataset_frozen: import corporate actions before freezing")
        prepared: list[dict[str, Any]] = []
        for action in actions:
            event_time = utc_iso(normalise_timestamp(action["event_time"]))
            available_at = utc_iso(normalise_timestamp(action.get("available_at", action["event_time"])))
            prepared.append(
                {
                    "kind": action.get("kind", "corporate_action"),
                    "event_time": event_time,
                    "available_at": available_at,
                    "payload": {key: value for key, value in action.items() if key not in {"event_time", "available_at", "kind"}},
                }
            )
        return self.store.add_dataset_events(dataset_id, dataset["instrument_id"], prepared)

    def auxiliary_events(
        self, dataset_id: str, *, kind: str | None = None, available_until: str | None = None
    ) -> list[dict[str, Any]]:
        return self.store.dataset_events(dataset_id, kind=kind, available_until=available_until)

    # --- helpers -----------------------------------------------------------------

    def _latest_revision(self, instrument_id: str, timeframe: str, data_level: str) -> dict[str, Any] | None:
        rows = [
            row
            for row in self.store.list_datasets(instrument_id=instrument_id, limit=500)
            if row.get("timeframe") == timeframe and row.get("data_level", "ohlcv") == data_level
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: int(row.get("revision", 1)))

    @staticmethod
    def _dataset_id(instrument_id: str, timeframe: str, data_level: str, revision: int) -> str:
        digest = stable_hash({"instrument": instrument_id, "timeframe": timeframe, "level": data_level})[:10]
        return f"ds_{digest}_{timeframe}_r{revision}"


def dataset_manifest_digest(datasets: Sequence[dict[str, Any]]) -> str:
    """One hash covering every dataset revision a run touched."""
    payload = sorted(
        f"{item.get('dataset_id')}:{item.get('revision')}:{item.get('content_checksum')}" for item in datasets
    )
    return hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()[:32]


__all__ = [
    "MarketDataCatalog",
    "SPLIT_ORDER",
    "SplitWindow",
    "chronological_splits",
    "dataset_manifest_digest",
    "walk_forward_folds",
]
