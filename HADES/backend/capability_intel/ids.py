"""Stable, unambiguous capability identifiers for the HADES broker.

Public model-facing IDs use provider-qualified forms:

    core:fs:read
    plugin:markitdown:convert
    mcp:github:create_issue

Internal ``CanonicalCapability.canonical_id`` values (e.g. ``markitdown:tool:convert``)
remain valid aliases during migration.
"""

from __future__ import annotations

import re
from typing import Any, Literal

ProviderKind = Literal["core", "plugin", "mcp"]

_CAP_ID_RE = re.compile(
    r"^(?P<provider>core|plugin|mcp):(?P<provider_id>[^:]+):(?P<action>.+)$",
    re.IGNORECASE,
)


def make_capability_id(provider: ProviderKind, provider_id: str, action: str) -> str:
    pid = str(provider_id or "").strip().lower()
    act = str(action or "").strip()
    if not pid or not act:
        raise ValueError("provider_id and action are required for capability ids")
    # Avoid double-prefixing mcp:mcp:github → strip leading mcp: from provider_id.
    if provider == "mcp" and pid.startswith("mcp:"):
        pid = pid[4:]
    if provider == "plugin" and pid.startswith("plugin:"):
        pid = pid[7:]
    return f"{provider}:{pid}:{act}"


def parse_capability_id(capability_id: str) -> tuple[ProviderKind, str, str] | None:
    raw = str(capability_id or "").strip()
    if not raw:
        return None
    match = _CAP_ID_RE.match(raw)
    if not match:
        return None
    provider = match.group("provider").lower()  # type: ignore[assignment]
    return provider, match.group("provider_id").lower(), match.group("action")


def detect_provider_kind(plugin: dict[str, Any] | None, *, plugin_id: str = "") -> ProviderKind:
    pid = str(plugin_id or (plugin or {}).get("id") or "").strip().lower()
    if not pid or pid in {"hades", "hades.core", "hades.native"}:
        return "core"
    plugin_type = str((plugin or {}).get("plugin_type") or "").strip().lower()
    manifest = (plugin or {}).get("manifest") if isinstance((plugin or {}).get("manifest"), dict) else {}
    if plugin_type in {"mcp", "mcp-managed", "mcp_provider"} or pid.startswith("mcp:"):
        return "mcp"
    if isinstance(manifest.get("mcp"), dict):
        return "mcp"
    meta = (plugin or {}).get("metadata") if isinstance((plugin or {}).get("metadata"), dict) else {}
    if meta.get("mcp_managed") or meta.get("mcp_remote"):
        return "mcp"
    return "plugin"


def capability_id_for_tool(
    plugin: dict[str, Any] | None,
    tool: dict[str, Any],
    *,
    plugin_id: str | None = None,
) -> str:
    pid = str(plugin_id or (plugin or {}).get("id") or tool.get("plugin_id") or "").strip()
    action = str(tool.get("name") or tool.get("action") or "").strip()
    provider = detect_provider_kind(plugin, plugin_id=pid)
    # Public MCP ids drop the mcp: prefix from the plugin id segment.
    display_pid = pid[4:] if provider == "mcp" and pid.lower().startswith("mcp:") else pid
    return make_capability_id(provider, display_pid or "unknown", action or "unknown")


def capability_id_for_record(record: Any) -> str:
    """Derive the public broker id from a CanonicalCapability-like record."""
    extras = getattr(record, "extras", None) or {}
    if isinstance(extras, dict) and extras.get("capability_id"):
        return str(extras["capability_id"])
    plugin_id = str(getattr(record, "plugin_id", None) or getattr(record, "provider_id", "") or "")
    name = str(getattr(record, "name", "") or "")
    source = str(getattr(record, "source", "") or "").lower()
    kind = str(getattr(record, "kind", "") or "")
    if kind == "tool" and plugin_id:
        fake_plugin = {"id": plugin_id, "plugin_type": "mcp" if "mcp" in source or plugin_id.startswith("mcp:") else "tool"}
        return capability_id_for_tool(fake_plugin, {"name": name, "plugin_id": plugin_id})
    if plugin_id.startswith("mcp:") or "mcp" in source:
        action = name or str(getattr(record, "canonical_id", "")).split(":")[-1]
        display = plugin_id[4:] if plugin_id.lower().startswith("mcp:") else plugin_id
        return make_capability_id("mcp", display or "unknown", action or "unknown")
    if plugin_id and plugin_id not in {"hades", "hades.native", "hades.core"}:
        return make_capability_id("plugin", plugin_id, name or "unknown")
    return make_capability_id("core", "hades", name or str(getattr(record, "canonical_id", "unknown")))


def legacy_aliases(capability_id: str) -> list[str]:
    """Return alternate ids that may appear in older registry rows."""
    parsed = parse_capability_id(capability_id)
    if not parsed:
        return [capability_id]
    provider, provider_id, action = parsed
    aliases = [capability_id]
    if provider == "plugin":
        aliases.append(f"{provider_id}:tool:{action}")
        aliases.append(f"{provider_id}:{action}")
    elif provider == "mcp":
        aliases.append(f"mcp:{provider_id}:tool:{action}")
        aliases.append(f"mcp:{provider_id}:{action}")
        aliases.append(f"mcp__{provider_id}__{action}")
        aliases.append(action)
    elif provider == "core":
        aliases.append(f"hades.{action}" if not action.startswith("hades.") else action)
        aliases.append(f"hades:{action}")
    return aliases
