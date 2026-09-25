"""Sealed market datasets — immutable, hashed, provenance-bearing OHLCV versions."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath

from .ohlcv import OhlcvValidation, analyze_ohlcv_quality, validate_ohlcv_file
from .types import MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DatasetImmutableError(MarketSimError):
    def __init__(self, message: str) -> None:
        super().__init__("DATASET_IMMUTABLE", message, http_status=409)


@dataclass
class DataQualityReport:
    ok: bool
    bar_count: int
    start_ts: str | None
    end_ts: str | None
    content_hash: str
    duplicate_timestamps: int = 0
    unordered_pairs: int = 0
    known_gaps: list[dict[str, Any]] = field(default_factory=list)
    outlier_bars: list[dict[str, Any]] = field(default_factory=list)
    timezone: str = "UTC"
    adjustment_mode: str = "unspecified"
    schema_ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SealedMarketDataset:
    """Immutable market dataset version used by sealed experiments / runs."""

    dataset_id: str
    source_id: str
    version: int
    content_hash: str
    symbol: str
    timeframe: str
    kind: str
    path: str
    start_ts: str | None
    end_ts: str | None
    bar_count: int
    provider: str
    venue: str
    instrument_family: str
    timezone: str
    adjustment_mode: str
    quality: dict[str, Any]
    provenance: dict[str, Any]
    sealed_at: str
    sealed: bool = True
    sealed_for: str | None = None  # trial_id / run_id that first sealed it
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_id": self.source_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "kind": self.kind,
            "path": self.path,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "bar_count": self.bar_count,
            "provider": self.provider,
            "venue": self.venue,
            "instrument_family": self.instrument_family,
            "timezone": self.timezone,
            "adjustment_mode": self.adjustment_mode,
            "quality": self.quality,
            "provenance": self.provenance,
            "sealed_at": self.sealed_at,
            "sealed": self.sealed,
            "sealed_for": self.sealed_for,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "truth": {
                "immutable_once_sealed": True,
                "correction_requires_new_version": True,
            },
        }


@dataclass
class ImportResult:
    status: str  # QUARANTINED | INVALID | READY | SEALED
    relative_path: str
    content_hash: str
    quality: DataQualityReport
    dataset: SealedMarketDataset | None = None
    quarantine_path: str | None = None
    errors: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "quality": self.quality.public_dict(),
            "dataset": self.dataset.public_dict() if self.dataset else None,
            "quarantine_path": self.quarantine_path,
            "errors": self.errors,
        }


def _quality_from_validation(validation: OhlcvValidation, analysis: dict[str, Any]) -> DataQualityReport:
    errors = list(analysis.get("errors") or [])
    if validation.error:
        errors.append(validation.error)
    ok = bool(validation.ok) and not errors and int(analysis.get("duplicate_timestamps") or 0) == 0
    return DataQualityReport(
        ok=ok,
        bar_count=validation.bar_count,
        start_ts=validation.start_ts,
        end_ts=validation.end_ts,
        content_hash=validation.content_hash,
        duplicate_timestamps=int(analysis.get("duplicate_timestamps") or 0),
        unordered_pairs=int(analysis.get("unordered_pairs") or 0),
        known_gaps=list(analysis.get("known_gaps") or []),
        outlier_bars=list(analysis.get("outlier_bars") or []),
        timezone=str(analysis.get("timezone") or "UTC"),
        adjustment_mode=str(analysis.get("adjustment_mode") or "unspecified"),
        schema_ok=bool(analysis.get("schema_ok", validation.ok)),
        errors=errors,
        warnings=list(analysis.get("warnings") or []),
        operations=list(analysis.get("operations") or []),
    )


class MarketDatasetPipeline:
    """Canonical import pipeline around MarketDataStore / filesystem root.

    RAW → QUARANTINE → SCHEMA → TIMESTAMP NORM → TZ → DUPES → ORDER → GAPS →
    OUTLIERS → PROVENANCE → HASH → (optional) SEALED.
    """

    QUARANTINE_DIR = ".quarantine"

    def __init__(self, markets_root: Path, store: Any) -> None:
        self.markets_root = Path(markets_root)
        self.store = store

    def ensure_root(self) -> Path:
        self.markets_root.mkdir(parents=True, exist_ok=True)
        (self.markets_root / self.QUARANTINE_DIR).mkdir(parents=True, exist_ok=True)
        return self.markets_root

    def _abs_under_root(self, relative_or_abs: str | Path) -> Path:
        root = self.markets_root.resolve()
        candidate = Path(relative_or_abs)
        try:
            if candidate.is_absolute():
                resolved = candidate.resolve()
                safe_relpath(root, resolved)
                return resolved
            return safe_join(root, *Path(str(relative_or_abs)).parts)
        except PathEscapeError as exc:
            raise MarketSimError("PATH_ESCAPE", str(exc), http_status=400) from exc

    def quarantine_copy(self, absolute_src: Path, *, label: str | None = None) -> Path:
        self.ensure_root()
        digest = sha256_file(absolute_src)[:16]
        name = label or absolute_src.name
        dest = self.markets_root / self.QUARANTINE_DIR / f"{digest}_{name}"
        shutil.copy2(absolute_src, dest)
        return dest

    def import_file(
        self,
        relative_path: str,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        provider: str = "csv_local",
        venue: str = "",
        instrument_family: str = "equity",
        timezone: str = "UTC",
        adjustment_mode: str = "unspecified",
        seal: bool = False,
        sealed_for: str | None = None,
        source_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ImportResult:
        """Run the full validation pipeline on a file already under markets_root."""
        path = self._abs_under_root(relative_path)
        rel = str(safe_relpath(self.markets_root.resolve(), path))
        if not path.is_file():
            raise MarketSimError("DATA_NOT_FOUND", f"Market file not found: {rel}", http_status=404)

        qpath = self.quarantine_copy(path)
        q_rel = str(safe_relpath(self.markets_root.resolve(), qpath))

        validation = validate_ohlcv_file(path)
        analysis = analyze_ohlcv_quality(path, timezone=timezone, adjustment_mode=adjustment_mode)
        quality = _quality_from_validation(validation, analysis)
        quality.operations.append(
            {
                "op": "quarantine_copy",
                "from": rel,
                "to": q_rel,
                "at": utc_now(),
                "silent_repair": False,
            }
        )

        if not quality.ok:
            return ImportResult(
                status="INVALID",
                relative_path=rel,
                content_hash=quality.content_hash or validation.content_hash,
                quality=quality,
                quarantine_path=q_rel,
                errors=list(quality.errors),
            )

        from .ohlcv import infer_symbol_timeframe

        inferred_symbol, inferred_tf = infer_symbol_timeframe(path)
        now = utc_now()
        prov = {
            "source": "filesystem",
            "provider": provider,
            "import_timestamp": now,
            "original_path": rel,
            "quarantine_path": q_rel,
            **(provenance or {}),
        }
        dataset = SealedMarketDataset(
            dataset_id=str(uuid.uuid4()),
            source_id=source_id or "",
            version=1,
            content_hash=quality.content_hash,
            symbol=(symbol or inferred_symbol).upper(),
            timeframe=timeframe or inferred_tf,
            kind="ohlcv",
            path=rel,
            start_ts=quality.start_ts,
            end_ts=quality.end_ts,
            bar_count=quality.bar_count,
            provider=provider,
            venue=venue,
            instrument_family=instrument_family,
            timezone=timezone,
            adjustment_mode=adjustment_mode,
            quality=quality.public_dict(),
            provenance=prov,
            sealed_at=now if seal else "",
            sealed=bool(seal),
            sealed_for=sealed_for if seal else None,
            created_at=now,
            metadata={},
        )
        if seal:
            existing = self.store.get_sealed_dataset_by_hash(quality.content_hash)
            if existing is not None:
                dataset = existing
            else:
                dataset.source_id = source_id or dataset.source_id
                dataset = self.store.insert_sealed_dataset(dataset)
            return ImportResult(
                status="SEALED",
                relative_path=rel,
                content_hash=quality.content_hash,
                quality=quality,
                dataset=dataset,
                quarantine_path=q_rel,
            )
        return ImportResult(
            status="READY",
            relative_path=rel,
            content_hash=quality.content_hash,
            quality=quality,
            dataset=dataset,
            quarantine_path=q_rel,
        )

    def seal_existing(
        self,
        *,
        source_id: str,
        content_hash: str,
        path: str,
        symbol: str,
        timeframe: str,
        start_ts: str | None,
        end_ts: str | None,
        bar_count: int,
        quality: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        provider: str = "csv_local",
        venue: str = "",
        instrument_family: str = "equity",
        timezone: str = "UTC",
        adjustment_mode: str = "unspecified",
        sealed_for: str | None = None,
        parent_dataset_id: str | None = None,
    ) -> SealedMarketDataset:
        """Seal a dataset version. Corrections must call this with a new hash → new version."""
        existing = self.store.get_sealed_dataset_by_hash(content_hash)
        if existing is not None:
            return existing

        prior = self.store.list_sealed_datasets(source_id=source_id, limit=1)
        next_version = (prior[0].version + 1) if prior else 1
        if parent_dataset_id:
            parent = self.store.get_sealed_dataset(parent_dataset_id)
            if parent is None:
                raise MarketSimError("DATASET_NOT_FOUND", parent_dataset_id, http_status=404)
            if parent.content_hash == content_hash:
                raise DatasetImmutableError(
                    "Cannot re-seal identical content; sealed datasets are immutable"
                )
            next_version = parent.version + 1

        now = utc_now()
        dataset = SealedMarketDataset(
            dataset_id=str(uuid.uuid4()),
            source_id=source_id,
            version=next_version,
            content_hash=content_hash,
            symbol=symbol.upper(),
            timeframe=timeframe,
            kind="ohlcv",
            path=path,
            start_ts=start_ts,
            end_ts=end_ts,
            bar_count=bar_count,
            provider=provider,
            venue=venue,
            instrument_family=instrument_family,
            timezone=timezone,
            adjustment_mode=adjustment_mode,
            quality=dict(quality or {}),
            provenance=dict(provenance or {"sealed_at": now}),
            sealed_at=now,
            sealed=True,
            sealed_for=sealed_for,
            created_at=now,
        )
        return self.store.insert_sealed_dataset(dataset)

    def assert_mutable(self, content_hash: str) -> None:
        """Refuse silent mutation of a sealed content hash."""
        existing = self.store.get_sealed_dataset_by_hash(content_hash)
        if existing is not None and existing.sealed:
            raise DatasetImmutableError(
                f"Dataset {existing.dataset_id} (hash={content_hash[:12]}…) is sealed; "
                "corrections require a new dataset version/hash"
            )
