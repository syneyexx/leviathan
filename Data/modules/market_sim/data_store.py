"""Market data discovery under a configured data root (filesystem + DB metadata)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath

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
        return {
            "markets_root": str(root),
            "configured": configured,
            "exists": exists,
            "sources_indexed": len(sources),
            "sources_ready": ready,
            "truth": {
                "files_on_filesystem": True,
                "db_holds_metadata_only": True,
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
