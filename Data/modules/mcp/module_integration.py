"""ModuleManager ↔ McpBridge integration for module.json mcp.servers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bridge import McpBridge
from .errors import McpError


def load_module_mcp_metadata(manifest_path: Path | str | None) -> dict[str, Any] | None:
    if not manifest_path:
        return None
    path = Path(manifest_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    mcp = data.get("mcp")
    return mcp if isinstance(mcp, dict) else None


def register_module_mcp(
    bridge: McpBridge,
    *,
    module_id: str,
    manifest_path: str | None,
) -> list[Any]:
    """Best-effort: register module-declared MCP servers into the ONE bridge."""
    meta = load_module_mcp_metadata(manifest_path)
    if not meta:
        return []
    root = Path(manifest_path).parent if manifest_path else None
    try:
        return bridge.register_servers_from_module(module_id, meta, module_root=root)
    except McpError:
        # required MCP failure — re-raise for caller policy
        raise


def unregister_module_mcp(bridge: McpBridge, module_id: str) -> int:
    return bridge.unregister_module_servers(module_id)
