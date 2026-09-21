"""Extensible MCP server catalog (verified against public docs; no invented endpoints)."""

from __future__ import annotations

from typing import Any

# Official remote GitHub MCP (Streamable HTTP): https://api.githubcopilot.com/mcp/
# Auth: Bearer PAT (OAuth also exists for hosts that implement the MCP OAuth flow).
# Source: github/github-mcp-server README (remote server section).

# Official Hugging Face MCP: https://huggingface.co/mcp
# Auth: Authorization Bearer HF token, or OAuth via ?login for supporting clients.
# Source: huggingface/hf-mcp-server README.

CATALOG: list[dict[str, Any]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "Officiële remote GitHub MCP-server (repos, issues, PRs, Actions).",
        "transport": "streamable_http",
        "endpoint_url": "https://api.githubcopilot.com/mcp/",
        "auth_methods": ["bearer", "oauth"],
        "default_auth_method": "bearer",
        "auth_hint": "Gebruik een GitHub Personal Access Token als Bearer, of OAuth wanneer de server metadata adverteert.",
        "docs_url": "https://github.com/github/github-mcp-server",
        "requires_network": True,
        "oauth_supported": True,
        "oauth_note": "OAuth vereist MCP protected-resource discovery + browser PKCE. PAT blijft de eenvoudigste desktopoptie.",
        "headers": {},
        "plugin_id": None,
    },
    {
        "id": "huggingface",
        "name": "Hugging Face",
        "description": "Officiële Hugging Face Hub MCP-server (modellen, datasets, Spaces).",
        "transport": "streamable_http",
        "endpoint_url": "https://huggingface.co/mcp",
        "auth_methods": ["bearer", "oauth"],
        "default_auth_method": "bearer",
        "auth_hint": "Authorization: Bearer <HF_TOKEN>. OAuth via clients die https://huggingface.co/mcp?login ondersteunen.",
        "docs_url": "https://huggingface.co/docs/hub/hf-mcp-server",
        "requires_network": True,
        "oauth_supported": True,
        "oauth_note": "Browser-OAuth met ?login; of eigen HF token als Bearer.",
        "headers": {},
        "plugin_id": None,
    },
    {
        "id": "chrome-devtools-mcp",
        "name": "Chrome DevTools MCP",
        "description": "Bestaande HADES-plugin: Chrome DevTools via lokale stdio MCP-bridge.",
        "transport": "stdio",
        "auth_methods": ["none"],
        "default_auth_method": "none",
        "auth_hint": "Geen remote auth; beheerd via Plugin Manager (npx chrome-devtools-mcp).",
        "docs_url": "https://github.com/ChromeDevTools/chrome-devtools-mcp",
        "requires_network": False,
        "oauth_supported": False,
        "plugin_id": "chrome-devtools-mcp",
        "command_template": {
            "executable": "npx",
            "args": ["-y", "chrome-devtools-mcp@latest"],
        },
        "owned_by_plugin": True,
    },
    {
        "id": "desktop-commander-mcp",
        "name": "Desktop Commander MCP",
        "description": "Bestaande HADES-plugin: Desktop Commander via lokale stdio MCP-bridge.",
        "transport": "stdio",
        "auth_methods": ["none"],
        "default_auth_method": "none",
        "auth_hint": "Geen remote auth; beheerd via Plugin Manager.",
        "docs_url": "https://github.com/wonderwhy-er/DesktopCommanderMCP",
        "requires_network": False,
        "oauth_supported": False,
        "plugin_id": "desktop-commander-mcp",
        "command_template": {
            "executable": "npx",
            "args": ["-y", "@wonderwhy-er/desktop-commander@latest"],
        },
        "owned_by_plugin": True,
    },
    {
        "id": "custom",
        "name": "Aangepaste MCP-server",
        "description": "Eigen lokale stdio- of externe Streamable HTTP MCP-server.",
        "transport": "custom",
        "auth_methods": ["none", "bearer", "oauth"],
        "default_auth_method": "none",
        "auth_hint": "Kies transport en authenticatie zelf. OAuth alleen wanneer de server discovery ondersteunt.",
        "docs_url": None,
        "requires_network": None,
        "oauth_supported": True,
        "plugin_id": None,
    },
]


def catalog_items() -> list[dict[str, Any]]:
    return [dict(item) for item in CATALOG]


def get_catalog_item(catalog_id: str) -> dict[str, Any] | None:
    for item in CATALOG:
        if item["id"] == catalog_id:
            return dict(item)
    return None


def enrich_catalog_status(
    items: list[dict[str, Any]],
    servers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mark each catalog entry using the most truthful status available.

    Callers that annotate servers with ``connection_status_effective`` should
    never be downgraded back to a stale persisted connection status. Modern MCP
    servers use ``ready`` rather than ``connected`` after successful discovery;
    both represent an operational catalog entry.
    """
    by_catalog: dict[str, list[dict[str, Any]]] = {}
    by_plugin: dict[str, dict[str, Any]] = {}
    for server in servers:
        cid = server.get("catalog_id")
        if cid:
            by_catalog.setdefault(str(cid), []).append(server)
        if server.get("owner_plugin_id"):
            by_plugin[str(server["owner_plugin_id"])] = server
    out: list[dict[str, Any]] = []
    for item in items:
        entry = dict(item)
        matches = list(by_catalog.get(item["id"]) or [])
        plugin_id = item.get("plugin_id")
        if plugin_id and plugin_id in by_plugin and by_plugin[plugin_id] not in matches:
            matches.append(by_plugin[plugin_id])
        entry["configured_servers"] = [
            {
                "id": s["id"],
                "name": s["name"],
                "connection_status": s.get("connection_status_effective") or s.get("connection_status"),
                "owner_kind": s.get("owner_kind"),
                "owner_plugin_id": s.get("owner_plugin_id"),
            }
            for s in matches
        ]
        if not matches:
            entry["status"] = "available"
        else:
            statuses = {
                str(s.get("connection_status_effective") or s.get("connection_status") or "")
                for s in matches
            }
            if statuses & {"connected", "ready"}:
                entry["status"] = "connected"
            elif statuses & {"policy_blocked", "auth_required", "error"}:
                entry["status"] = "blocked_or_incomplete"
            else:
                entry["status"] = "configured"
        out.append(entry)
    return out
