"""Canonical capability registry over native + plugin + MCP sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_registry_cache import invalidate_plugin_registry_cache

from .adapters.native import native_capabilities
from .contracts import AdaptationResult, CanonicalCapability
from .normalize import adapt_package
from .policy import apply_runtime_health
from .store import (
    cache_invalidate,
    ensure_capability_schema,
    load_capabilities,
    remove_plugin_capabilities,
    replace_native_capabilities,
    replace_plugin_capabilities,
)
from .taxonomy import NATIVE_PROVIDER_ID


class CapabilityRegistry:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db
        self._memory: list[CanonicalCapability] = []
        if db is not None:
            ensure_capability_schema(db)

    def refresh_native(self) -> list[CanonicalCapability]:
        records = native_capabilities()
        self._upsert(records, plugin_id=None)
        if self.db is not None:
            replace_native_capabilities(self.db, records)
            cache_invalidate(self.db, "route:")
        return records

    def refresh_plugin(self, plugin: dict[str, Any], tools: list[dict[str, Any]] | None = None) -> AdaptationResult:
        root = Path(str(plugin.get("local_path") or "")).expanduser()
        result = adapt_package(
            root if str(root) and root.exists() else None,
            plugin=plugin,
            manifest=plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else None,
            tools=tools,
        )
        for record in result.capabilities:
            apply_runtime_health(record, plugin)
        plugin_id = str(plugin.get("id") or "")
        self._drop_plugin(plugin_id)
        self._memory.extend(result.capabilities)
        if self.db is not None and plugin_id:
            replace_plugin_capabilities(self.db, plugin_id, result.capabilities)
            cache_invalidate(self.db, "route:")
            cache_invalidate(self.db, f"plugin:{plugin_id}")
        invalidate_plugin_registry_cache()
        return result

    def ingest_mcp_tools(self, plugin: dict[str, Any], tools: list[dict[str, Any]]) -> AdaptationResult:
        """Re-normalize after MCP expand/mirror. Same registry, not a parallel catalog."""
        return self.refresh_plugin(plugin, tools=tools)

    def drop_plugin(self, plugin_id: str) -> None:
        self._drop_plugin(plugin_id)
        if self.db is not None:
            remove_plugin_capabilities(self.db, plugin_id)
            cache_invalidate(self.db)
        invalidate_plugin_registry_cache()

    def all(self) -> list[CanonicalCapability]:
        by_id: dict[str, CanonicalCapability] = {}
        if self.db is not None:
            for item in load_capabilities(self.db):
                by_id[item.canonical_id] = item
        for item in self._memory:
            by_id.setdefault(item.canonical_id, item)
        if not any(item.provider_id == NATIVE_PROVIDER_ID or item.source == "native" for item in by_id.values()):
            for item in native_capabilities():
                by_id[item.canonical_id] = item
        return list(by_id.values())

    def by_kind(self, kind: str) -> list[CanonicalCapability]:
        return [item for item in self.all() if item.kind == kind]

    def get(self, canonical_id: str) -> CanonicalCapability | None:
        for item in self.all():
            if item.canonical_id == canonical_id:
                return item
        return None

    def snapshot(self) -> dict[str, Any]:
        records = self.all()
        groups: dict[str, int] = {}
        for item in records:
            groups[item.kind] = groups.get(item.kind, 0) + 1
        return {
            "count": len(records),
            "by_kind": groups,
            "providers": sorted({item.provider_id for item in records if item.provider_id}),
        }

    def _upsert(self, records: list[CanonicalCapability], *, plugin_id: str | None) -> None:
        keep = [item for item in self._memory if (item.plugin_id or None) != plugin_id]
        keep.extend(records)
        self._memory = keep

    def _drop_plugin(self, plugin_id: str) -> None:
        self._memory = [item for item in self._memory if item.plugin_id != plugin_id]


_REGISTRY: CapabilityRegistry | None = None


def get_registry(db: Any | None = None) -> CapabilityRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = CapabilityRegistry(db)
        _REGISTRY.refresh_native()
    elif db is not None and _REGISTRY.db is None:
        _REGISTRY.db = db
    return _REGISTRY


def reset_registry() -> None:
    global _REGISTRY
    _REGISTRY = None
