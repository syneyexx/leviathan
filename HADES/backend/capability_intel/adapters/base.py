"""Package adapter protocol.

External representations are parsed here. Core routing never branches on
ecosystem names such as ``claude`` or a specific plugin id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class AdapterHit:
    adapter_id: str
    confidence: float
    notes: list[str] = field(default_factory=list)


class PackageAdapter(Protocol):
    adapter_id: str

    def detect(self, root: Path, manifest: dict[str, Any] | None = None) -> AdapterHit:
        """Return confidence in [0, 1]. Zero means this adapter should not run."""

    def parse(
        self,
        root: Path,
        *,
        plugin: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a raw adaptation payload (capabilities + unsupported)."""


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[PackageAdapter] = []

    def register(self, adapter: PackageAdapter) -> None:
        ids = {item.adapter_id for item in self._adapters}
        if adapter.adapter_id in ids:
            self._adapters = [item for item in self._adapters if item.adapter_id != adapter.adapter_id]
        self._adapters.append(adapter)

    def adapters(self) -> list[PackageAdapter]:
        return list(self._adapters)

    def detect_all(self, root: Path, manifest: dict[str, Any] | None = None) -> list[AdapterHit]:
        hits: list[AdapterHit] = []
        for adapter in self._adapters:
            try:
                hit = adapter.detect(root, manifest)
            except Exception:
                continue
            if hit.confidence > 0:
                hits.append(hit)
        hits.sort(key=lambda item: item.confidence, reverse=True)
        return hits

    def parse_applicable(
        self,
        root: Path,
        *,
        plugin: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
        min_confidence: float = 0.15,
    ) -> list[tuple[str, dict[str, Any]]]:
        results: list[tuple[str, dict[str, Any]]] = []
        for adapter in self._adapters:
            try:
                hit = adapter.detect(root, manifest)
                if hit.confidence < min_confidence:
                    continue
                payload = adapter.parse(root, plugin=plugin, manifest=manifest)
            except Exception as exc:
                results.append((adapter.adapter_id, {"error": str(exc), "capabilities": [], "unsupported": []}))
                continue
            if isinstance(payload, dict):
                results.append((adapter.adapter_id, payload))
        return results


def default_registry() -> AdapterRegistry:
    from .claude_upstream import ClaudeUpstreamAdapter
    from .convention import ConventionAdapter
    from .hades_manifest import HadesManifestAdapter
    from .mcp_discovery import McpDiscoveryAdapter

    registry = AdapterRegistry()
    registry.register(HadesManifestAdapter())
    registry.register(ConventionAdapter())
    registry.register(ClaudeUpstreamAdapter())
    registry.register(McpDiscoveryAdapter())
    return registry
