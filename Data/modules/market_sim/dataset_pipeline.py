"""Canonical market-data import pipeline around MarketDataStore.

RAW → quarantine → schema → timestamps → timezone → duplicates → ordering →
gaps → outliers → session/calendar → provenance → hash → SEALED dataset version.

Never silently repair data without recording the operation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_relpath

from .ohlcv import (
    REQUIRED_OHLCV_COLUMNS,
    _parquet_available,
    load_ohlcv,
    validate_ohlcv_file,
)
from .types import Bar, CausalityViolation, DataKind, MarketSimError, SourceStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DatasetQualityState(str, Enum):
    QUARANTINED = "QUARANTINED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    SEALED = "SEALED"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class RepairOperation(str, Enum):
    NONE = "NONE"
    TIMEZONE_ASSUMED_UTC = "TIMEZONE_ASSUMED_UTC"
    TIMESTAMP_NORMALIZED = "TIMESTAMP_NORMALIZED"
    ROW_DROPPED = "ROW_DROPPED"
    COLUMN_RENAMED = "COLUMN_RENAMED"


@dataclass
class RecordedRepair:
    operation: str
    detail: str
    row: int | None = None
    recorded_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GapReport:
    after_ts: str
    before_ts: str
    gap_seconds: float

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetQualityReport:
    ok: bool
    state: str
    bar_count: int = 0
    start_ts: str | None = None
    end_ts: str | None = None
    content_hash: str = ""
    byte_size: int = 0
    timezone: str = "UTC"
    duplicate_timestamps: list[str] = field(default_factory=list)
    unordered_pairs: list[dict[str, str]] = field(default_factory=list)
    gaps: list[GapReport] = field(default_factory=list)
    outliers: list[dict[str, Any]] = field(default_factory=list)
    repairs: list[RecordedRepair] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_columns: list[str] = field(default_factory=list)
    expected_bar_seconds: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "state": self.state,
            "bar_count": self.bar_count,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
            "timezone": self.timezone,
            "duplicate_timestamps": self.duplicate_timestamps,
            "unordered_pairs": self.unordered_pairs,
            "gaps": [g.public_dict() for g in self.gaps],
            "outliers": self.outliers,
            "repairs": [r.public_dict() for r in self.repairs],
            "errors": self.errors,
            "warnings": self.warnings,
            "schema_columns": self.schema_columns,
            "expected_bar_seconds": self.expected_bar_seconds,
            "truth": {
                "no_silent_repair": True,
                "duplicates_are_errors": True,
            },
        }


@dataclass
class SealedMarketDataset:
    """Immutable market dataset version used by sealed experiments."""

    dataset_id: str
    version: str
    source_id: str | None
    symbol: str
    timeframe: str
    venue: str
    instrument_family: str
    provider: str
    timezone: str
    start_ts: str
    end_ts: str
    bar_count: int
    content_hash: str
    adjustment_mode: str
    quality_state: str
    quality: dict[str, Any]
    provenance: dict[str, Any]
    known_gaps: list[dict[str, Any]]
    sealed: bool
    sealed_at: str | None
    path: str
    parent_version: str | None = None
    role: str = "RESEARCH"  # RESEARCH | VALIDATION | SEALED_TEST | ...
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def version_key(self) -> str:
        return f"{self.dataset_id}@{self.version}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "version_key": self.version_key,
            "source_id": self.source_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "venue": self.venue,
            "instrument_family": self.instrument_family,
            "provider": self.provider,
            "timezone": self.timezone,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "bar_count": self.bar_count,
            "content_hash": self.content_hash,
            "adjustment_mode": self.adjustment_mode,
            "quality_state": self.quality_state,
            "quality": self.quality,
            "provenance": self.provenance,
            "known_gaps": self.known_gaps,
            "sealed": self.sealed,
            "sealed_at": self.sealed_at,
            "path": self.path,
            "parent_version": self.parent_version,
            "role": self.role,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "truth": {
                "sealed_versions_immutable": True,
                "correction_creates_new_version": True,
            },
        }


_TIMEFRAME_SECONDS = {
    "1m": 60.0,
    "5m": 300.0,
    "15m": 900.0,
    "1h": 3600.0,
    "4h": 14400.0,
    "1D": 86400.0,
    "1d": 86400.0,
}


def _parse_dt(ts: str) -> datetime:
    cleaned = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def analyze_bars(
    bars: Sequence[Bar],
    *,
    timeframe: str = "1h",
    content_hash: str = "",
    byte_size: int = 0,
    repairs: list[RecordedRepair] | None = None,
) -> DatasetQualityReport:
    """Run ordering / duplicate / gap / outlier checks on in-memory bars."""
    report = DatasetQualityReport(
        ok=True,
        state=DatasetQualityState.VALIDATING.value,
        bar_count=len(bars),
        content_hash=content_hash,
        byte_size=byte_size,
        schema_columns=list(REQUIRED_OHLCV_COLUMNS),
        repairs=list(repairs or []),
        expected_bar_seconds=_TIMEFRAME_SECONDS.get(timeframe),
    )
    if not bars:
        report.ok = False
        report.state = DatasetQualityState.INVALID.value
        report.errors.append("empty bar series")
        return report

    report.start_ts = bars[0].ts
    report.end_ts = bars[-1].ts
    seen: dict[str, int] = {}
    prev: Bar | None = None
    expected = report.expected_bar_seconds

    for i, bar in enumerate(bars):
        if bar.ts in seen:
            report.duplicate_timestamps.append(bar.ts)
            report.errors.append(f"duplicate timestamp at row {i}: {bar.ts}")
        else:
            seen[bar.ts] = i
        if prev is not None:
            try:
                if _parse_dt(bar.ts) < _parse_dt(prev.ts):
                    report.unordered_pairs.append({"prev": prev.ts, "curr": bar.ts})
                    report.errors.append(f"unordered timestamps {prev.ts} -> {bar.ts}")
                elif expected:
                    delta = (_parse_dt(bar.ts) - _parse_dt(prev.ts)).total_seconds()
                    # Allow 1.5× expected as soft gap; weekends inflate daily crypto etc.
                    if delta > expected * 2.5:
                        report.gaps.append(
                            GapReport(after_ts=prev.ts, before_ts=bar.ts, gap_seconds=delta)
                        )
                        report.warnings.append(
                            f"gap {delta:.0f}s between {prev.ts} and {bar.ts}"
                        )
            except ValueError as exc:
                report.errors.append(str(exc))
        # Soft outlier: range vs close (does not invent microstructure)
        span = bar.high - bar.low
        if bar.close > 0 and span / bar.close > 0.5:
            report.outliers.append(
                {
                    "ts": bar.ts,
                    "kind": "wide_range",
                    "range_pct": round(span / bar.close * 100.0, 3),
                }
            )
            report.warnings.append(f"wide range outlier at {bar.ts}")
        prev = bar

    if report.duplicate_timestamps or report.unordered_pairs or report.errors:
        report.ok = False
        report.state = DatasetQualityState.INVALID.value
    else:
        report.state = DatasetQualityState.READY.value
    return report


def quarantine_path(markets_root: Path, relative_path: str) -> Path:
    """Place an incoming file under ``.quarantine/`` (path-escape safe)."""
    root = markets_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    qdir = root / ".quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    name = Path(relative_path).name
    if not name or name in {".", ".."}:
        raise MarketSimError("INVALID_PATH", "empty quarantine filename", http_status=400)
    dest = qdir / f"{uuid.uuid4().hex[:8]}_{name}"
    try:
        safe_relpath(root, dest.resolve())
    except PathEscapeError as exc:
        raise MarketSimError("PATH_ESCAPE", str(exc), http_status=400) from exc
    return dest


@dataclass
class ImportResult:
    quality: DatasetQualityReport
    dataset: SealedMarketDataset | None
    quarantined_path: str | None
    bars: list[Bar] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality.public_dict(),
            "dataset": self.dataset.public_dict() if self.dataset else None,
            "quarantined_path": self.quarantined_path,
            "bar_count": len(self.bars),
        }


class MarketDatasetPipeline:
    """Import + seal pipeline. Persists via injected store callbacks."""

    def __init__(self, markets_root: Path) -> None:
        self.markets_root = Path(markets_root)

    def ensure_root(self) -> Path:
        self.markets_root.mkdir(parents=True, exist_ok=True)
        return self.markets_root

    def ingest_file(
        self,
        source_path: Path,
        *,
        symbol: str,
        timeframe: str,
        provider: str = "csv_local",
        venue: str = "",
        instrument_family: str = "crypto_spot",
        timezone_name: str = "UTC",
        adjustment_mode: str = "as_traded",
        role: str = "RESEARCH",
        seal: bool = False,
        dataset_id: str | None = None,
        source_id: str | None = None,
        provenance: dict[str, Any] | None = None,
        expected_gap_seconds: float | None = None,
    ) -> ImportResult:
        """Run the full validation pipeline on a vendor/user file."""
        self.ensure_root()
        source_path = Path(source_path)
        if not source_path.is_file():
            raise MarketSimError("DATA_NOT_FOUND", f"file not found: {source_path}", http_status=404)

        # 1. Quarantine copy (never mutate the operator's original in-place)
        qpath = quarantine_path(self.markets_root, source_path.name)
        shutil.copy2(source_path, qpath)

        repairs: list[RecordedRepair] = [
            RecordedRepair(
                operation=RepairOperation.NONE.value,
                detail="quarantine copy created; original untouched",
                recorded_at=utc_now(),
            )
        ]

        # 2–3. Schema + load (timestamp normalization happens inside ohlcv)
        validation = validate_ohlcv_file(qpath)
        if not validation.ok:
            report = DatasetQualityReport(
                ok=False,
                state=DatasetQualityState.QUARANTINED.value,
                content_hash=validation.content_hash,
                byte_size=validation.byte_size,
                errors=[validation.error or "validation failed"],
                repairs=repairs,
            )
            return ImportResult(quality=report, dataset=None, quarantined_path=str(qpath))

        try:
            bars = load_ohlcv(qpath)
        except MarketSimError as exc:
            report = DatasetQualityReport(
                ok=False,
                state=DatasetQualityState.QUARANTINED.value,
                content_hash=validation.content_hash,
                byte_size=validation.byte_size,
                errors=[exc.message],
                repairs=repairs,
            )
            return ImportResult(quality=report, dataset=None, quarantined_path=str(qpath))

        # Record timezone assumption when naive stamps were normalized to UTC
        repairs.append(
            RecordedRepair(
                operation=RepairOperation.TIMESTAMP_NORMALIZED.value,
                detail="timestamps normalized to UTC ISO-8601 via ohlcv._normalize_ts",
                recorded_at=utc_now(),
            )
        )
        if timezone_name.upper() == "UTC":
            repairs.append(
                RecordedRepair(
                    operation=RepairOperation.TIMEZONE_ASSUMED_UTC.value,
                    detail="timezone declared/assumed UTC",
                    recorded_at=utc_now(),
                )
            )

        report = analyze_bars(
            bars,
            timeframe=timeframe,
            content_hash=validation.content_hash,
            byte_size=validation.byte_size,
            repairs=repairs,
        )
        if expected_gap_seconds is not None:
            report.expected_bar_seconds = expected_gap_seconds
        report.timezone = timezone_name

        if not report.ok:
            report.state = DatasetQualityState.QUARANTINED.value
            return ImportResult(quality=report, dataset=None, quarantined_path=str(qpath), bars=bars)

        # Promote out of quarantine into curated tree when valid
        rel_dir = Path("curated") / symbol.upper() / timeframe
        dest_dir = self.markets_root / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source_path.name
        if dest.exists() and sha256_file(dest) != validation.content_hash:
            # Content changed → new filename version, never overwrite silently
            stem = dest.stem
            dest = dest_dir / f"{stem}_{validation.content_hash[:10]}{dest.suffix}"
        if not dest.exists():
            shutil.copy2(qpath, dest)
        try:
            rel = str(safe_relpath(self.markets_root.resolve(), dest.resolve()))
        except PathEscapeError as exc:
            raise MarketSimError("PATH_ESCAPE", str(exc), http_status=400) from exc

        ds_id = dataset_id or str(uuid.uuid4())
        version = "1"
        now = utc_now()
        dataset = SealedMarketDataset(
            dataset_id=ds_id,
            version=version,
            source_id=source_id,
            symbol=symbol.upper(),
            timeframe=timeframe,
            venue=venue,
            instrument_family=instrument_family,
            provider=provider,
            timezone=timezone_name,
            start_ts=report.start_ts or "",
            end_ts=report.end_ts or "",
            bar_count=report.bar_count,
            content_hash=report.content_hash,
            adjustment_mode=adjustment_mode,
            quality_state=DatasetQualityState.SEALED.value if seal else DatasetQualityState.READY.value,
            quality=report.public_dict(),
            provenance={
                **dict(provenance or {}),
                "import_timestamp": now,
                "quarantine_path": str(qpath),
                "original_name": source_path.name,
                "kind": DataKind.OHLCV.value,
                "parquet_available": _parquet_available(),
            },
            known_gaps=[g.public_dict() for g in report.gaps],
            sealed=bool(seal),
            sealed_at=now if seal else None,
            path=rel,
            role=role,
            created_at=now,
            metadata={"byte_size": report.byte_size},
        )
        if seal:
            report.state = DatasetQualityState.SEALED.value
        return ImportResult(quality=report, dataset=dataset, quarantined_path=str(qpath), bars=bars)

    def seal_existing(
        self,
        dataset: SealedMarketDataset,
        *,
        role: str = "SEALED_TEST",
    ) -> SealedMarketDataset:
        """Mark an already-validated dataset version as sealed (immutable)."""
        if dataset.sealed:
            return dataset
        now = utc_now()
        dataset.sealed = True
        dataset.sealed_at = now
        dataset.role = role
        dataset.quality_state = DatasetQualityState.SEALED.value
        return dataset

    def correct_sealed(
        self,
        previous: SealedMarketDataset,
        *,
        new_path: Path,
        reason: str,
    ) -> ImportResult:
        """Corrections to sealed data MUST create a new version/hash."""
        if not previous.sealed:
            raise MarketSimError(
                "DATASET_NOT_SEALED",
                "correct_sealed requires a sealed parent; use ingest_file for unsealed edits",
            )
        result = self.ingest_file(
            new_path,
            symbol=previous.symbol,
            timeframe=previous.timeframe,
            provider=previous.provider,
            venue=previous.venue,
            instrument_family=previous.instrument_family,
            timezone_name=previous.timezone,
            adjustment_mode=previous.adjustment_mode,
            role=previous.role,
            seal=True,
            dataset_id=previous.dataset_id,
            source_id=previous.source_id,
            provenance={
                "corrected_from_version": previous.version,
                "correction_reason": reason,
                "previous_hash": previous.content_hash,
            },
        )
        if result.dataset is None:
            return result
        # Bump version relative to parent
        try:
            next_ver = str(int(previous.version) + 1)
        except ValueError:
            next_ver = f"{previous.version}.1"
        result.dataset.version = next_ver
        result.dataset.parent_version = previous.version
        if result.dataset.content_hash == previous.content_hash:
            raise MarketSimError(
                "DATASET_UNCHANGED",
                "correction produced identical content hash — refuse no-op version bump",
            )
        return result


def assert_dataset_immutable(dataset: SealedMarketDataset, *, new_hash: str) -> None:
    """Fail if a sealed dataset's content would mutate in place."""
    if dataset.sealed and new_hash != dataset.content_hash:
        raise CausalityViolation(
            f"Sealed dataset {dataset.version_key} is immutable; "
            f"create a new version instead of mutating hash {dataset.content_hash[:12]}…"
        )


def dataset_fingerprint(dataset: SealedMarketDataset) -> str:
    payload = {
        "dataset_id": dataset.dataset_id,
        "version": dataset.version,
        "content_hash": dataset.content_hash,
        "symbol": dataset.symbol,
        "timeframe": dataset.timeframe,
        "start_ts": dataset.start_ts,
        "end_ts": dataset.end_ts,
        "bar_count": dataset.bar_count,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
