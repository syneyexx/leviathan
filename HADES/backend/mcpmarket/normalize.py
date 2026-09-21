"""Normalize MCPMarket listings into CanonicalCapability records."""

from __future__ import annotations

from typing import Any

from capability_intel.normalize import normalize_raw_capability
from capability_intel.taxonomy import NATIVE_PROVIDER_ID
from hades_brain.traits import infer_traits
from plugin_runtime_v2 import normalize_trust

PROVIDER_ID = "mcpmarket"


def _plugin_stub(listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": PROVIDER_ID,
        "enabled": False,
        "status": "needs_setup",
        "trust": "untrusted",
        "health": "needs_setup",
        "version": str(listing.get("version") or ""),
        "permissions": [],
    }


def listing_to_capabilities(listing: dict[str, Any]) -> dict[str, Any]:
    slug = str(listing.get("slug") or listing.get("name") or "entry").strip()
    kind_hint = str(listing.get("kind_hint") or "mcp_server")
    capabilities: list[Any] = []
    unsupported: list[dict[str, Any]] = []
    extras = {
        "marketplace": "mcpmarket",
        "source_url": listing.get("source_url"),
        "publisher": listing.get("publisher"),
        "github": listing.get("github") or [],
        "json_ld_extras": listing.get("json_ld_extras") or {},
        "untrusted": True,
        "instruction_authority": False,
        "injection_flagged": bool(listing.get("injection_flagged")),
        "requires_operator_approval": True,
        "auto_install": False,
        "provenance": {
            "marketplace": "mcpmarket",
            "entry": slug,
            "source_url": listing.get("source_url"),
            "publisher": listing.get("publisher"),
            "last_discovery": listing.get("discovered_at"),
            "trust": "untrusted",
            "connection_state": "discovered",
        },
    }
    if listing.get("unknown_fields"):
        extras["unknown_fields"] = listing.get("unknown_fields")
        unsupported.append({"path": slug, "claimed_kind": str(listing.get("claimed_kind") or ""), "reason": "unknown_metadata_preserved"})

    plugin = _plugin_stub(listing)
    if kind_hint == "skill":
        raw = {
            "id": slug,
            "name": listing.get("name") or slug,
            "kind": "skill",
            "description": listing.get("description") or "",
            "from": "mcpmarket.skill",
            "trust_requirements": "untrusted",
            "health": "unknown",
            "side_effect_class": "none",
            "cost_class": "cheap",
            "provider_id": PROVIDER_ID,
            "domains": ["mcp", "skills"],
            "intents": ["retrieve"],
        }
        record = normalize_raw_capability(raw, plugin=plugin, adapter_id="mcpmarket")
        if record:
            record.availability = False
            record.health = "unknown"
            record.trust_requirements = normalize_trust("untrusted")
            record.extras.update(extras)
            record.extras["traits"] = infer_traits(kind="skill", extras=record.extras)
            if listing.get("executable"):
                record.extras["contains_executable_claim"] = True
                record.extras["executable_untrusted"] = True
            capabilities.append(record)
    else:
        raw_provider = {
            "id": slug,
            "name": listing.get("name") or slug,
            "kind": "mcp_provider",
            "description": listing.get("description") or "",
            "from": "mcpmarket.mcp_provider",
            "trust_requirements": "untrusted",
            "provider_id": PROVIDER_ID,
            "domains": ["mcp"],
            "intents": ["discover_tools"],
            "side_effect_class": "network",
            "cost_class": "moderate",
        }
        provider = normalize_raw_capability(raw_provider, plugin=plugin, adapter_id="mcpmarket")
        if provider:
            provider.availability = False
            provider.health = "needs_setup"
            provider.trust_requirements = normalize_trust("untrusted")
            provider.extras.update(extras)
            if listing.get("toolkit_shaped") or listing.get("toolkit"):
                provider.extras["normalized_from"] = "toolkit"
                provider.extras["prefer_focused_surface"] = True
            provider.extras["traits"] = infer_traits(
                kind="mcp_provider",
                side_effect_class="network",
                extras=provider.extras,
                declared=["networked", "requires_auth"] if listing.get("requires_auth") else ["networked"],
            )
            capabilities.append(provider)
        tools = listing.get("tools") if isinstance(listing.get("tools"), list) else []
        for tool in tools[:40]:
            if not isinstance(tool, dict):
                continue
            tool_id = str(tool.get("name") or tool.get("id") or "").strip()
            if not tool_id:
                continue
            raw_tool = {
                "id": f"{slug}.{tool_id}",
                "name": tool_id,
                "kind": "tool",
                "description": tool.get("description") or "",
                "from": "mcpmarket.declared_tool",
                "input_schema": tool.get("input_schema") or tool.get("inputSchema") or {},
                "provider_id": PROVIDER_ID,
            }
            rec = normalize_raw_capability(raw_tool, plugin=plugin, adapter_id="mcpmarket")
            if rec:
                rec.availability = False
                rec.trust_requirements = "untrusted"
                rec.extras.update({"parent": slug, "untrusted": True, "not_executed": True})
                capabilities.append(rec)

    for key, value in (listing.get("extensions") or {}).items():
        unsupported.append({"path": f"{slug}.{key}", "claimed_kind": str(type(value).__name__), "reason": "unknown_extension"})

    return {
        "capabilities": capabilities,
        "unsupported": unsupported,
        "adapter_id": "mcpmarket",
        "trust": "untrusted",
        "instruction_authority": False,
    }


def unknown_metadata_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve unknown marketplace fields without inventing semantics."""
    known = {
        "name",
        "description",
        "slug",
        "publisher",
        "github",
        "tools",
        "kind_hint",
        "source_url",
        "version",
        "toolkit",
        "toolkit_shaped",
    }
    unknown = {key: payload[key] for key in payload if key not in known}
    return {"unknown_fields": unknown, "invented": False}
