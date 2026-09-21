"""HADES native manifest adapter (hades-plugin.json, including legacy)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AdapterHit


def _read_manifest(root: Path, manifest: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(manifest, dict) and manifest:
        return dict(manifest)
    path = root / "hades-plugin.json"
    if not path.is_file():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class HadesManifestAdapter:
    adapter_id = "hades_manifest"

    def detect(self, root: Path, manifest: dict[str, Any] | None = None) -> AdapterHit:
        data = _read_manifest(root, manifest)
        if not data:
            return AdapterHit(self.adapter_id, 0.0)
        confidence = 0.95 if (root / "hades-plugin.json").is_file() or manifest else 0.7
        notes = []
        if "capabilities" in data and isinstance(data.get("capabilities"), dict):
            notes.append("semantic_capabilities_block")
        if data.get("plugin_type"):
            notes.append(f"legacy_plugin_type={data.get('plugin_type')}")
        return AdapterHit(self.adapter_id, confidence, notes)

    def parse(
        self,
        root: Path,
        *,
        plugin: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = _read_manifest(root, manifest)
        if plugin and isinstance(plugin.get("manifest"), dict) and not data:
            data = dict(plugin["manifest"])
        capabilities: list[dict[str, Any]] = []
        semantic = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
        # Newer semantic block (skills/tools/agents/...) — do not confuse with
        # Plugin Runtime v2 effect contracts (effects/cost_class/...).
        semantic_keys = {"skills", "knowledge", "tools", "agents", "services", "workflows", "resources", "tool_providers", "mcp_providers"}
        if any(key in semantic for key in semantic_keys):
            for kind, items in semantic.items():
                if kind not in semantic_keys or not isinstance(items, list):
                    continue
                mapped_kind = {
                    "skills": "skill",
                    "knowledge": "knowledge",
                    "tools": "tool",
                    "agents": "agent",
                    "services": "service",
                    "workflows": "workflow",
                    "resources": "resource",
                    "tool_providers": "tool_provider",
                    "mcp_providers": "mcp_provider",
                }[kind]
                for raw in items:
                    if not isinstance(raw, dict):
                        continue
                    capabilities.append({**raw, "kind": mapped_kind, "from": "manifest.capabilities"})
        # Legacy tools[] remain executable tool capabilities.
        for raw in data.get("tools") or []:
            if not isinstance(raw, dict):
                continue
            capabilities.append(
                {
                    "id": raw.get("id") or raw.get("name"),
                    "name": raw.get("name") or raw.get("id"),
                    "description": raw.get("description") or "",
                    "kind": "tool",
                    "input_contract": raw.get("input_schema") or {},
                    "output_contract": raw.get("output_schema") or {},
                    "effects": (raw.get("capabilities") or {}).get("effects") if isinstance(raw.get("capabilities"), dict) else None,
                    "cost_class": (raw.get("capabilities") or {}).get("cost_class") if isinstance(raw.get("capabilities"), dict) else None,
                    "latency_class": (raw.get("capabilities") or {}).get("latency_class") if isinstance(raw.get("capabilities"), dict) else None,
                    "side_effect_class": (raw.get("capabilities") or {}).get("side_effect_class") if isinstance(raw.get("capabilities"), dict) else None,
                    "failure_modes": (raw.get("capabilities") or {}).get("failure_modes") if isinstance(raw.get("capabilities"), dict) else None,
                    "from": "manifest.tools",
                    "tool": raw,
                }
            )
        plugin_type = str(data.get("plugin_type") or (plugin or {}).get("plugin_type") or "").lower()
        if plugin_type == "service":
            capabilities.append(
                {
                    "id": f"{data.get('id') or (plugin or {}).get('id') or root.name}.service",
                    "name": data.get("name") or (plugin or {}).get("name") or root.name,
                    "description": data.get("description") or "",
                    "kind": "service",
                    "from": "legacy.plugin_type",
                }
            )
        if plugin_type in {"mcp", "mcp-managed", "mcp_provider"}:
            capabilities.append(
                {
                    "id": f"{data.get('id') or (plugin or {}).get('id') or root.name}.mcp",
                    "name": data.get("name") or root.name,
                    "kind": "mcp_provider",
                    "from": "legacy.plugin_type",
                }
            )
        # A plugin that exposes tools is also a tool_provider.
        if any(item.get("kind") == "tool" for item in capabilities):
            capabilities.append(
                {
                    "id": f"{data.get('id') or (plugin or {}).get('id') or root.name}.provider",
                    "name": data.get("name") or (plugin or {}).get("name") or root.name,
                    "kind": "tool_provider",
                    "from": "derived.tool_provider",
                }
            )
        return {"capabilities": capabilities, "unsupported": [], "manifest": data}
