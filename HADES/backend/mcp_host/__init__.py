"""HADES first-class MCP management host.

Long-lived sessions live in the FastAPI process (not per CLI invoke).
Plugin-owned MCP servers stay owned by Plugin Manager — never double-started.
"""

from __future__ import annotations

from mcp_host.lifecycle import ensure_mcp_manager, make_mcp_call_handler, mcp_health_snapshot
from mcp_host.manager import McpManager, get_mcp_manager, is_mcp_tool_metadata, set_mcp_manager
from mcp_host.routes import mount_mcp_routes

__all__ = [
    "McpManager",
    "get_mcp_manager",
    "set_mcp_manager",
    "is_mcp_tool_metadata",
    "mount_mcp_routes",
    "ensure_mcp_manager",
    "mcp_health_snapshot",
    "make_mcp_call_handler",
]
