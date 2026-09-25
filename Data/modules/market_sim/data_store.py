"""Market data discovery under a configured data root (filesystem + DB metadata)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath

from .dataset_pipeline import MarketDatasetPipeline, SealedMarketDataset
from .ohlcv import infer_symbol_timeframe, validate_ohlcv_file
from .store import MarketSimStore
from .types import DataKind, MarketDataSource, MarketSimError, SourceStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MarketDataStore:
    """Indexes real market files under markets_root. Large files stay on disk."""

    SUPPORTED_SUFFIXES = {".csv", ".txt", ".parquet"}

    def __init__(self, store: MarketSimStore, markets_root: Path) -> None:
        self.store = store
        self.markets_root = Path(markets_root)
        self.pipeline = MarketDatasetPipeline(self.markets_root)

    def ensure_root(self) -> Path:
        self.markets_root.mkdir(parents=True, exist_ok=True)
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

    def scan(self, *, register: bool = True) -> list[MarketDataSource]:
        self.ensure_root()
        found: list[MarketDataSource] = []
        for path in sorted(self.markets_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
                continue
            if path.name.startswith("."):
                continue
            try:
                rel_parts = safe_relpath(self.markets_root.resolve(), path.resolve()).parts
            except PathEscapeError:
                continue
            if any(part.startswith(".") for part in rel_parts):
                continue
            try:
                rel = str(safe_relpath(self.markets_root.resolve(), path.resolve()))
            except PathEscapeError:
                continue
            source = self.inspect_path(rel, register=register)
            found.append(source)
        return found

    def inspect_path(self, relative_path: str, *, register: bool = True) -> MarketDataSource:
        path = self._abs_under_root(relative_path)
        rel = str(safe_relpath(self.markets_root.resolve(), path))
        symbol, timeframe = infer_symbol_timeframe(path)
        validation = validate_ohlcv_file(path)
        now = utc_now()
        status = SourceStatus.READY.value if validation.ok else SourceStatus.INVALID.value
        existing = self.store.get_source_by_path(rel)
        source_id = existing.source_id if existing else str(uuid.uuid4())
        source = MarketDataSource(
            source_id=source_id,
            symbol=symbol,
            timeframe=timeframe,
            kind=DataKind.OHLCV.value,
            path=rel,
            content_hash=validation.content_hash,
            status=status,
            bar_count=validation.bar_count,
            start_ts=validation.start_ts,
            end_ts=validation.end_ts,
            byte_size=validation.byte_size,
            validation_error=validation.error,
            metadata={
                "parquet_available": validation.parquet_available,
                "absolute_path": str(path),
                "duplicate_count": validation.duplicate_count,
                "gap_count": validation.gap_count,
                "quality": validation.quality,
            },
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        if register:
            self.store.upsert_source(source)
        return source

    def register_file(
        self,
        relative_path: str,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> MarketDataSource:
        source = self.inspect_path(relative_path, register=True)
        if symbol or timeframe:
            source.symbol = (symbol or source.symbol).upper()
            source.timeframe = timeframe or source.timeframe
            source.updated_at = utc_now()
            self.store.upsert_source(source)
        return source

    def import_and_validate(
        self,
        absolute_or_relative: str | Path,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        seal: bool = False,
        role: str = "RESEARCH",
        provider: str = "csv_local",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the T1 quarantine → validate → hash → (optional) seal pipeline."""
        candidate = Path(absolute_or_relative)
        if not candidate.is_absolute():
            path = self._abs_under_root(candidate)
        else:
            path = candidate
            try:
                safe_relpath(self.markets_root.resolve(), path.resolve())
            except PathEscapeError:
                pass
        inferred_symbol, inferred_tf = infer_symbol_timeframe(path)
        result = self.pipeline.ingest_file(
            path,
            symbol=(symbol or inferred_symbol).upper(),
            timeframe=timeframe or inferred_tf,
            provider=provider,
            seal=seal,
            role=role,
            provenance=provenance,
        )
        source = None
        dataset_payload = None
        if result.dataset is not None:
            dataset_payload = result.dataset.public_dict()
            self.store.upsert_dataset_version(dataset_payload)
            source = self.register_file(
                result.dataset.path,
                symbol=result.dataset.symbol,
                timeframe=result.dataset.timeframe,
            )
            source.metadata = {
                **dict(source.metadata or {}),
                "dataset_id": result.dataset.dataset_id,
                "dataset_version": result.dataset.version,
                "sealed": result.dataset.sealed,
                "quality_state": result.dataset.quality_state,
                "known_gaps": result.dataset.known_gaps,
                "provenance": result.dataset.provenance,
            }
            source.updated_at = utc_now()
            self.store.upsert_source(source)
        return {
            "import": result.public_dict(),
            "source": source.public_dict() if source else None,
            "dataset": dataset_payload,
        }

    def seal_dataset(self, dataset_id: str, version: str, *, role: str = "SEALED_TEST") -> dict[str, Any]:
        existing = self.store.get_dataset_version(dataset_id, version)
        if existing is None:
            raise MarketSimError("DATASET_NOT_FOUND", f"{dataset_id}@{version}", http_status=404)
        ds = SealedMarketDataset(
            dataset_id=existing["dataset_id"],
            version=existing["version"],
            source_id=existing.get("source_id"),
            symbol=existing["symbol"],
            timeframe=existing["timeframe"],
            venue=existing.get("venue") or "",
            instrument_family=existing.get("instrument_family") or "",
            provider=existing.get("provider") or "csv_local",
            timezone=existing.get("timezone") or "UTC",
            start_ts=existing["start_ts"],
            end_ts=existing["end_ts"],
            bar_count=int(existing.get("bar_count") or 0),
            content_hash=existing["content_hash"],
            adjustment_mode=existing.get("adjustment_mode") or "as_traded",
            quality_state=existing.get("quality_state") or "READY",
            quality=dict(existing.get("quality") or {}),
            provenance=dict(existing.get("provenance") or {}),
            known_gaps=list(existing.get("known_gaps") or []),
            sealed=bool(existing.get("sealed")),
            sealed_at=existing.get("sealed_at"),
            path=existing["path"],
            parent_version=existing.get("parent_version"),
            role=existing.get("role") or "RESEARCH",
            created_at=existing.get("created_at") or "",
            metadata=dict(existing.get("metadata") or {}),
        )
        sealed = self.pipeline.seal_existing(ds, role=role)
        payload = sealed.public_dict()
        self.store.upsert_dataset_version(payload)
        return payload

    def correct_sealed_dataset(
        self,
        dataset_id: str,
        version: str,
        new_file: str | Path,
        *,
        reason: str,
    ) -> dict[str, Any]:
        existing = self.store.get_dataset_version(dataset_id, version)
        if existing is None:
            raise MarketSimError("DATASET_NOT_FOUND", f"{dataset_id}@{version}", http_status=404)
        if not existing.get("sealed"):
            raise MarketSimError("DATASET_NOT_SEALED", "parent must be sealed")
        parent = SealedMarketDataset(
            dataset_id=existing["dataset_id"],
            version=existing["version"],
            source_id=existing.get("source_id"),
            symbol=existing["symbol"],
            timeframe=existing["timeframe"],
            venue=existing.get("venue") or "",
            instrument_family=existing.get("instrument_family") or "",
            provider=existing.get("provider") or "csv_local",
            timezone=existing.get("timezone") or "UTC",
            start_ts=existing["start_ts"],
            end_ts=existing["end_ts"],
            bar_count=int(existing.get("bar_count") or 0),
            content_hash=existing["content_hash"],
            adjustment_mode=existing.get("adjustment_mode") or "as_traded",
            quality_state=existing.get("quality_state") or "SEALED",
            quality=dict(existing.get("quality") or {}),
            provenance=dict(existing.get("provenance") or {}),
            known_gaps=list(existing.get("known_gaps") or []),
            sealed=True,
            sealed_at=existing.get("sealed_at"),
            path=existing["path"],
            parent_version=existing.get("parent_version"),
            role=existing.get("role") or "SEALED_TEST",
            created_at=existing.get("created_at") or "",
            metadata=dict(existing.get("metadata") or {}),
        )
        path = Path(new_file)
        if not path.is_absolute():
            path = self._abs_under_root(path)
        result = self.pipeline.correct_sealed(parent, new_path=path, reason=reason)
        if result.dataset is None:
            return {"import": result.public_dict(), "dataset": None}
        payload = result.dataset.public_dict()
        self.store.upsert_dataset_version(payload)
        return {"import": result.public_dict(), "dataset": payload}

    def list_sources(self, *, status: str | None = None, limit: int = 200) -> list[MarketDataSource]:
        return self.store.list_sources(status=status, limit=limit)

    def get_source(self, source_id: str) -> MarketDataSource:
        source = self.store.get_source(source_id)
        if source is None:
            raise MarketSimError("SOURCE_NOT_FOUND", f"Unknown source: {source_id}", http_status=404)
        return source

    def absolute_path_for(self, source: MarketDataSource) -> Path:
        return self._abs_under_root(source.path)

    def health(self) -> dict[str, Any]:
        root = self.markets_root
        configured = bool(str(root).strip())
        exists = root.is_dir()
        sources = self.store.list_sources(limit=5000)
        ready = sum(1 for s in sources if s.status == SourceStatus.READY.value)
        sealed = self.store.list_dataset_versions(sealed=True, limit=5000)
        return {
            "markets_root": str(root),
            "configured": configured,
            "exists": exists,
            "sources_indexed": len(sources),
            "sources_ready": ready,
            "sealed_datasets": len(sealed),
            "truth": {
                "files_on_filesystem": True,
                "db_holds_metadata_only": True,
                "sealed_versions_immutable": True,
            },
        }

    def rehash(self, source_id: str) -> MarketDataSource:
        source = self.get_source(source_id)
        path = self.absolute_path_for(source)
        if not path.is_file():
            source.status = SourceStatus.UNAVAILABLE.value
            source.validation_error = "file missing"
            source.updated_at = utc_now()
            self.store.upsert_source(source)
            return source
        source.content_hash = sha256_file(path)
        return self.inspect_path(source.path, register=True)
