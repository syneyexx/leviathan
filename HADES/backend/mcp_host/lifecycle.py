"""Canonical MCP manager lifecycle — one bootstrap path for module + lifespan."""

from __future__ import annotations

import logging
from typing import Any, Callable

from mcp_host.manager import McpManager, get_mcp_manager, set_mcp_manager

log = logging.getLogger("hades.mcp")


def normalize_mcp_server_id(plugin: dict[str, Any], tool: dict[str, Any]) -> str:
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    server_id = str(meta.get("mcp_server_id") or "").removeprefix("mcp:")
    plugin_id = str(plugin.get("id") or "")
    if plugin_id.startswith("mcp:"):
        server_id = plugin_id[4:]
    return server_id


def make_mcp_call_handler(manager: McpManager) -> Callable[..., dict[str, Any]]:
    def _handler(
        plugin: dict[str, Any],
        tool: dict[str, Any],
        validated: dict[str, Any],
        *,
        invocation_type: str = "autonomous",
        approved_by_user: bool = False,
    ) -> dict[str, Any]:
        meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
        server_id = normalize_mcp_server_id(plugin, tool)
        remote = str(meta.get("mcp_tool") or "")
        if not server_id or not remote:
            raise RuntimeError("mcp_managed tool mist server/tool metadata")
        return manager.call_managed_tool(
            server_id,
            remote,
            validated if isinstance(validated, dict) else {},
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
        )

    return _handler


def ensure_mcp_manager(
    *,
    platform_db: Any,
    plugin_manager: Any,
    settings_provider: Callable[[], dict[str, Any]],
    approval_service: Any | None = None,
) -> McpManager | None:
    """Create or rebind the singleton MCP manager. Never raises to callers."""
    try:
        mgr = get_mcp_manager()
        if mgr is None or getattr(mgr, "platform_db", None) is not platform_db:
            mgr = McpManager(
                platform_db,
                plugin_manager=plugin_manager,
                settings_provider=settings_provider,
                approval_service=approval_service,
            )
            set_mcp_manager(mgr)
        else:
            mgr.plugin_manager = plugin_manager
            mgr.settings_provider = settings_provider
            if approval_service is not None:
                mgr.approval_service = approval_service
        if plugin_manager is not None and hasattr(plugin_manager, "set_mcp_call_handler"):
            plugin_manager.set_mcp_call_handler(make_mcp_call_handler(mgr))
        mgr.subsystem_status = "ok"
        mgr.init_error = None
        return mgr
    except Exception as exc:
        log.warning("mcp_host_init_failed: %s", exc)
        try:
            existing = get_mcp_manager()
            if existing is not None:
                existing.subsystem_status = "error"
                existing.init_error = str(exc)
        except Exception:
            pass
        return None


def mcp_health_snapshot() -> dict[str, Any]:
    mgr = get_mcp_manager()
    if mgr is None:
        return {"id": "mcp", "label": "MCP host", "status": "warn", "detail": "MCP manager not initialized"}
    status = getattr(mgr, "subsystem_status", "ok") or "ok"
    detail = getattr(mgr, "init_error", None) or "MCP host ready"
    tone = "ok" if status == "ok" else "error"
    try:
        count = len(mgr.store.list_servers())
        detail = f"{count} servers configured" if status == "ok" else detail
    except Exception as exc:
        tone = "warn"
        detail = str(exc)
    return {"id": "mcp", "label": "MCP host", "status": tone, "detail": detail}
