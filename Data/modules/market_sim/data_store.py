"""Market data discovery under a configured data root (filesystem + DB metadata)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath

from .dataset_pipeline import MarketDatasetPipeline, SealedMarketDataset, analyze_bars
from .ohlcv import (
    infer_symbol_timeframe,
    iter_ohlcv,
    load_ohlcv,
    storage_format_for_path,
    validate_ohlcv_file,
    write_ohlcv_analytical,
)
from .pit_fabric import quality_with_pit_labels
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
        """Full scan helper — prefer ``scan_slice`` for production worker execution."""
        result = self.scan_slice(register=register, max_entries=1_000_000, max_directories=1_000_000)
        return list(result.get("sources") or [])

    def scan_slice(
        self,
        *,
        register: bool = True,
        max_entries: int = 200,
        max_directories: int = 100,
        cursor: dict[str, Any] | None = None,
        deep_validate: bool = True,
        cancel_check: Any | None = None,
    ) -> dict[str, Any]:
        """Bounded deterministic directory scan with checkpoint cursor.

        Does not follow symlinks. Only scans under markets_root. Skips hidden
        paths. Discovery does not require deep profile unless deep_validate=True.
        """
        self.ensure_root()
        root = self.markets_root.resolve()
        cur = dict(cursor or {})
        start_after = str(cur.get("last_relative_path") or "")
        discovered = int(cur.get("discovered_count") or 0)
        valid_count = int(cur.get("valid_candidate_count") or 0)
        skipped = int(cur.get("skipped_count") or 0)
        errors = int(cur.get("error_count") or 0)
        dirs_seen = int(cur.get("directories_seen") or 0)

        # Deterministic lexical walk — collect relative file paths in sorted order.
        # Do not follow symlinks (os.walk followlinks=False by default via Path.rglob
        # may still follow; use os.walk explicitly).
        import os

        candidates: list[str] = []
        dir_count = 0
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dir_count += 1
            # Skip hidden directories in-place (stable sorted)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel_dir = os.path.relpath(dirpath, root)
            if rel_dir == ".":
                rel_dir = ""
            if any(part.startswith(".") for part in Path(rel_dir).parts if part not in (".", "")):
                dirnames[:] = []
                continue
            for name in sorted(filenames):
                if name.startswith("."):
                    skipped += 1
                    continue
                suffix = Path(name).suffix.lower()
                if suffix not in self.SUPPORTED_SUFFIXES:
                    skipped += 1
                    continue
                rel = str(Path(rel_dir) / name) if rel_dir else name
                # Symlink escape protection
                abs_path = Path(dirpath) / name
                try:
                    if abs_path.is_symlink():
                        skipped += 1
                        continue
                    resolved = abs_path.resolve()
                    safe_relpath(root, resolved)
                except (PathEscapeError, OSError):
                    skipped += 1
                    errors += 1
                    continue
                candidates.append(rel.replace("\\", "/"))
            if dir_count >= max_directories + dirs_seen and not candidates:
                break

        candidates = sorted(set(candidates))
        # Resume after cursor
        if start_after:
            candidates = [c for c in candidates if c > start_after]

        sources: list[MarketDataSource] = []
        processed = 0
        last_rel = start_after
        for rel in candidates:
            if cancel_check is not None and cancel_check():
                break
            if processed >= max_entries:
                break
            if dir_count > max_directories + dirs_seen and processed >= max_entries:
                break
            try:
                if deep_validate:
                    source = self.inspect_path(rel, register=register)
                else:
                    source = self.inspect_path_metadata_only(rel, register=register)
                sources.append(source)
                discovered += 1
                if source.status == SourceStatus.READY.value:
                    valid_count += 1
            except Exception:  # noqa: BLE001
                errors += 1
            processed += 1
            last_rel = rel

        remaining = len(candidates) - processed
        done = remaining <= 0
        next_cursor = {
            "last_relative_path": last_rel,
            "discovered_count": discovered,
            "valid_candidate_count": valid_count,
            "skipped_count": skipped,
            "error_count": errors,
            "directories_seen": dirs_seen + dir_count,
            "root": str(root),
        }
        return {
            "sources": sources,
            "sources_public": [s.public_dict() for s in sources],
            "processed": processed,
            "remaining_estimate": max(0, remaining),
            "done": done,
            "cursor": next_cursor,
            "truth": {
                "bounded_scan": True,
                "deterministic_order": True,
                "no_symlink_follow": True,
                "markets_root_confined": True,
            },
        }

    def inspect_path_metadata_only(
        self, relative_path: str, *, register: bool = True
    ) -> MarketDataSource:
        """Cheap discovery metadata — no deep quality profile."""
        path = self._abs_under_root(relative_path)
        rel = str(safe_relpath(self.markets_root.resolve(), path))
        symbol, timeframe = infer_symbol_timeframe(path)
        now = utc_now()
        try:
            byte_size = path.stat().st_size
        except OSError:
            byte_size = 0
        existing = self.store.get_source_by_path(rel)
        source_id = existing.source_id if existing else str(uuid.uuid4())
        source = MarketDataSource(
            source_id=source_id,
            symbol=symbol,
            timeframe=timeframe,
            kind=DataKind.OHLCV.value,
            path=rel,
            content_hash=existing.content_hash if existing else "",
            status=SourceStatus.READY.value if existing else SourceStatus.DISCOVERED.value,
            bar_count=existing.bar_count if existing else 0,
            start_ts=existing.start_ts if existing else None,
            end_ts=existing.end_ts if existing else None,
            byte_size=byte_size,
            validation_error=None,
            metadata={
                "discovery_only": True,
                "absolute_path": str(path),
                "qualityVerdict": "UNMEASURED",
                **(
                    {"storageFormat": sf}
                    if (sf := storage_format_for_path(path))
                    else {}
                ),
            },
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        if register and existing:
            # Do not overwrite deep validation with discovery-only.
            pass
        elif register:
            self.store.upsert_source(source)
        return source

    def inspect_path(self, relative_path: str, *, register: bool = True) -> MarketDataSource:
        path = self._abs_under_root(relative_path)
        rel = str(safe_relpath(self.markets_root.resolve(), path))
        symbol, timeframe = infer_symbol_timeframe(path)
        validation = validate_ohlcv_file(path)
        now = utc_now()
        status = SourceStatus.READY.value if validation.ok else SourceStatus.INVALID.value
        validation_error = validation.error
        quality_payload: dict[str, Any] | None = validation.quality
        quality_verdict = "UNMEASURED"
        # Institutional W06 — schema parse is not a quality PASS; run streaming report.
        if validation.ok:
            try:
                from .dataset_pipeline import analyze_bars_streaming

                report = analyze_bars_streaming(
                    iter_ohlcv(path),
                    timeframe=timeframe,
                    content_hash=validation.content_hash,
                    byte_size=validation.byte_size,
                    adjustment_mode="as_traded",
                    survivorship_bias_risk="UNMEASURED",
                )
                quality_payload = quality_with_pit_labels(
                    report,
                    adjustment_mode="as_traded",
                    survivorship_mode="UNMEASURED",
                )
                quality_verdict = report.quality_verdict
                if not report.ok:
                    status = SourceStatus.INVALID.value
                    validation_error = "; ".join(report.errors[:3]) or "quality FAIL"
            except MarketSimError as exc:
                status = SourceStatus.INVALID.value
                validation_error = exc.message
                quality_verdict = "FAIL"
                quality_payload = {
                    "quality": "FAIL",
                    "qualityVerdict": "FAIL",
                    "errors": [exc.message],
                    "truth": {"parsed_csv_is_not_quality_pass": True},
                }
        elif validation.error:
            quality_verdict = "FAIL"
            quality_payload = {
                "quality": "FAIL",
                "qualityVerdict": "FAIL",
                "errors": [validation.error],
                "gap_count": validation.gap_count,
                "truth": {"parsed_csv_is_not_quality_pass": True},
            }
            if validation.error == "MARKET_DATA_CHANGED_DURING_VALIDATION":
                status = SourceStatus.INVALID.value
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
            validation_error=validation_error,
            metadata={
                "parquet_available": validation.parquet_available,
                "absolute_path": str(path),
                "duplicate_count": validation.duplicate_count,
                "gap_count": validation.gap_count,
                "quality": quality_payload,
                "qualityVerdict": quality_verdict,
                "streaming_validation": True,
                **(
                    {"storageFormat": sf}
                    if (sf := storage_format_for_path(path))
                    else {}
                ),
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
            if result.dataset.sealed:
                dataset_payload = self._attach_frozen_split(result.dataset)
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
        return self._attach_frozen_split(sealed)

    def _attach_frozen_split(self, sealed: SealedMarketDataset) -> dict[str, Any]:
        """Build and persist a frozen TRAIN/VAL/SEALED DatasetSplitManifest."""
        payload = sealed.public_dict()
        existing = self.store.get_split_manifest(
            dataset_id=sealed.dataset_id, dataset_version=sealed.version
        )
        if existing and existing.get("frozen"):
            payload = dict(payload)
            payload["split_manifest"] = existing
            meta = dict(payload.get("metadata") or {})
            meta["split_manifest_id"] = existing.get("manifest_id")
            meta.pop("split_manifest_error", None)
            payload["metadata"] = meta
            self.store.upsert_dataset_version(payload)
            return payload
        try:
            from .ohlcv import iter_ohlcv
            from .split_manifest import build_split_manifest_from_iter

            path = self._abs_under_root(sealed.path)
            if not path.is_file():
                raise MarketSimError("DATA_NOT_FOUND", f"sealed path missing: {path}", http_status=404)
            manifest = build_split_manifest_from_iter(
                iter_ohlcv(path),
                dataset_id=sealed.dataset_id,
                dataset_version=sealed.version,
                dataset_content_hash=sealed.content_hash,
                frozen=True,
            )
            stored = self.store.upsert_split_manifest(manifest.public_dict())
            payload = dict(payload)
            payload["split_manifest"] = stored
            meta = dict(payload.get("metadata") or {})
            meta["split_manifest_id"] = stored.get("manifest_id")
            payload["metadata"] = meta
            self.store.upsert_dataset_version(payload)
            return payload
        except MarketSimError as exc:
            meta = dict(payload.get("metadata") or {})
            meta["split_manifest_error"] = exc.code
            payload["metadata"] = meta
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

    def export_analytical(
        self,
        source_id: str,
        dest_dir: str | Path,
        *,
        prefer_parquet: bool = True,
    ) -> dict[str, Any]:
        """Export OHLCV for analytical use; prefer Parquet when pyarrow is present."""
        source = self.get_source(source_id)
        path = self.absolute_path_for(source)
        bars = list(iter_ohlcv(path))
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{source.symbol}_{source.timeframe}"
        dest = dest_dir / stem  # suffix chosen by write_ohlcv_analytical
        written = write_ohlcv_analytical(
            dest,
            bars,
            prefer_parquet=prefer_parquet,
            symbol=source.symbol,
        )
        return {
            "source_id": source_id,
            "symbol": source.symbol,
            "timeframe": source.timeframe,
            **written,
        }

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
