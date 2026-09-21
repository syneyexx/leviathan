"""Prepare MCP Host connection drafts. Never execute tools or install packages."""

from __future__ import annotations

from typing import Any

from .trust import inspect_listing


def prepare_connection(listing: dict[str, Any], *, operator_approved: bool = False) -> dict[str, Any]:
    inspection = inspect_listing(listing)
    endpoint = listing.get("endpoint_url") or listing.get("mcp_endpoint")
    transport = listing.get("transport")
    command = listing.get("command") if isinstance(listing.get("command"), dict) else None
    # Only honor transports that are already explicit in the listing. Do not guess npx/docker.
    draft: dict[str, Any] = {
        "name": listing.get("name") or listing.get("slug") or "mcpmarket-provider",
        "description": (listing.get("description") or "")[:400],
        "enabled": False,
        "auto_connect": False,
        "metadata": {
            "source": "mcpmarket",
            "slug": listing.get("slug"),
            "source_url": listing.get("source_url"),
            "trust": "untrusted",
            "marketplace_grants_trust": False,
            "requires_operator_install": command is None and not endpoint,
        },
        "auth_method": "none",
    }
    if isinstance(endpoint, str) and endpoint.startswith(("https://", "http://")):
        draft["transport"] = "streamable_http"
        draft["endpoint_url"] = endpoint
    elif isinstance(command, dict) and command.get("executable"):
        # Still a draft — MCP Host create requires operator POST. We never spawn the process here.
        draft["transport"] = "stdio"
        draft["command"] = {
            "executable": str(command.get("executable")),
            "args": list(command.get("args") or []),
        }
        draft["metadata"]["requires_operator_install"] = True
        draft["metadata"]["untrusted_install_command"] = True
    else:
        draft["transport"] = "custom"
        draft["status"] = "needs_setup"
        draft["reason"] = "no_verified_mcp_endpoint_in_listing"
    if not operator_approved:
        return {
            "allowed": False,
            "reason": "operator_approval_required",
            "draft": draft,
            "inspection": inspection,
            "executes": False,
            "installs": False,
        }
    if inspection["state"] == "policy_blocked":
        return {
            "allowed": False,
            "reason": "policy_blocked",
            "draft": None,
            "inspection": inspection,
            "executes": False,
            "installs": False,
        }
    return {
        "allowed": True,
        "reason": "draft_for_mcp_host",
        "draft": draft,
        "inspection": inspection,
        "executes": False,
        "installs": False,
        "next": "POST /api/mcp/servers then operator connect",
    }
