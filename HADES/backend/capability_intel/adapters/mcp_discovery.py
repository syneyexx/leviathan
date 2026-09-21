"""MCP discovery adapter.

MCP servers become mcp_provider records. Dynamically listed functions become
normalized tool capabilities. Actual expansion still goes through PluginManager
/ MCP host — this adapter only describes what is present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AdapterHit


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


class McpDiscoveryAdapter:
    adapter_id = "mcp_discovery"

    def detect(self, root: Path, manifest: dict[str, Any] | None = None) -> AdapterHit:
        notes: list[str] = []
        score = 0.0
        data = manifest if isinstance(manifest, dict) else {}
        mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
        if mcp:
            score = 0.8
            notes.append("manifest.mcp")
        tools = data.get("tools") if isinstance(data.get("tools"), list) else []
        names = {str(item.get("name", "")).lower() for item in tools if isinstance(item, dict)}
        if "list_tools" in names and "call_tool" in names:
            score = max(score, 0.85)
            notes.append("list_tools/call_tool")
        for name in ("mcp.json", ".mcp.json", "mcp_config.json"):
            if (root / name).is_file():
                score = max(score, 0.7)
                notes.append(name)
        if (root / ".mcp").is_dir():
            score = max(score, 0.4)
            notes.append(".mcp/")
        return AdapterHit(self.adapter_id, score, notes)

    def parse(
        self,
        root: Path,
        *,
        plugin: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capabilities: list[dict[str, Any]] = []
        plugin_id = str((plugin or {}).get("id") or (manifest or {}).get("id") or root.name)
        capabilities.append(
            {
                "id": f"{plugin_id}.mcp_provider",
                "name": (plugin or {}).get("name") or plugin_id,
                "kind": "mcp_provider",
                "from": "mcp.provider",
            }
        )
        tools = []
        if plugin and isinstance(plugin.get("tools"), list):
            tools = plugin["tools"]
        elif isinstance((manifest or {}).get("tools"), list):
            tools = (manifest or {})["tools"]
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
            name = str(tool.get("name") or "")
            if not (meta.get("mcp_remote") or meta.get("mcp_managed") or name.startswith("mcp__")):
                continue
            capabilities.append(
                {
                    "id": name,
                    "name": name,
                    "description": tool.get("description") or "",
                    "kind": "tool",
                    "input_contract": tool.get("input_schema") or {},
                    "from": "mcp.dynamic_tool",
                    "mcp_remote": True,
                }
            )
        for name in ("mcp.json", ".mcp.json", "mcp_config.json"):
            payload = _load_json(root / name)
            if not isinstance(payload, dict):
                continue
            servers = payload.get("mcpServers") or payload.get("servers") or {}
            if isinstance(servers, dict):
                for server_id, spec in servers.items():
                    capabilities.append(
                        {
                            "id": f"mcp:{server_id}",
                            "name": server_id,
                            "kind": "mcp_provider",
                            "from": "mcp.config",
                            "spec_keys": list(spec) if isinstance(spec, dict) else [],
                        }
                    )
        return {"capabilities": capabilities, "unsupported": []}
