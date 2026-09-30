"""Presentation helpers for Tools control-plane projections.

Descriptive only — never authorization. Origin/category/source are derived
from CapabilityCatalog metadata and provider provenance.
"""

from __future__ import annotations

from typing import Any

# Dutch display labels for known domain keys. Unknown → Overig.
DOMAIN_LABELS: dict[str, str] = {
    "web": "Web",
    "browser": "Web",
    "filesystem": "Bestand",
    "file": "Bestand",
    "coding": "Code",
    "code": "Code",
    "system": "Systeem",
    "media": "Media",
    "trading": "Trading",
    "market": "Trading",
    "data": "Data",
    "dataset": "Data",
    "communication": "Communicatie",
    "artifact": "Data",
    "knowledge": "Data",
    "memory": "Data",
    "research": "Data",
    "git": "Code",
    "mcp": "Systeem",
    "plugin": "Systeem",
    "module": "Systeem",
    "voice": "Media",
    "function": "Code",
}

SOURCE_LABELS: dict[str, str] = {
    "core": "Core",
    "builtin": "Core",
    "native": "Core",
    "internal": "Core",
    "plugin": "Plugin",
    "mcp": "MCP",
    "function": "Function",
    "module": "Module",
    "external": "External",
    "custom": "Custom",
    "browser": "Core",
    "media": "Core",
    "voice": "Core",
    "knowledge": "Core",
    "artifact": "Core",
}


def category_key(metadata: dict[str, Any] | None, *, capability_id: str = "") -> str:
    """Canonical category key from domains metadata (first domain) or id prefix."""
    meta = metadata or {}
    domains = meta.get("domains") or []
    if isinstance(domains, (list, tuple)) and domains:
        key = str(domains[0]).strip().lower()
        if key:
            return key
    if "." in capability_id:
        return capability_id.split(".", 1)[0].lower()
    return "overig"


def category_label(key: str) -> str:
    k = (key or "").strip().lower()
    if not k or k in {"overig", "unknown", "onbekend"}:
        return "Overig"
    return DOMAIN_LABELS.get(k) or k.replace("_", " ").title()


def resolve_origin(
    metadata: dict[str, Any] | None,
    *,
    provider_kind: str | None = None,
    in_plugin_bindings: bool = False,
) -> str:
    """Explicit ownership/origin for Tools KPIs and source chips.

    Priority:
      1. metadata.origin (canonical)
      2. plugin binding membership
      3. provider_kind mapping
    """
    meta = metadata or {}
    explicit = str(meta.get("origin") or "").strip().lower()
    if explicit:
        return explicit
    extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
    explicit_extra = str((extra or {}).get("origin") or "").strip().lower()
    if explicit_extra:
        return explicit_extra
    if in_plugin_bindings:
        return "plugin"
    kind = (provider_kind or "").strip().lower()
    if kind in {"builtin", "native", "internal"}:
        return "core"
    if kind in {"mcp", "plugin", "function", "module", "external", "custom"}:
        return kind
    if kind in {"browser", "media", "voice", "knowledge", "artifact"}:
        return "core"
    return kind or "core"


def source_label(origin: str) -> str:
    o = (origin or "").strip().lower()
    return SOURCE_LABELS.get(o) or (o.title() if o else "Core")


def tool_version(metadata: dict[str, Any] | None, *, fallback: str | None = None) -> str | None:
    """Tool/provider version — never metadata schema_version."""
    meta = metadata or {}
    for key in ("version", "tool_version", "provider_version"):
        value = meta.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
    for key in ("version", "tool_version", "provider_version"):
        value = (extra or {}).get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    if fallback is not None and str(fallback).strip():
        return str(fallback).strip()
    return None


def list_item_projection(
    definition: Any,
    *,
    plugin_capability_ids: set[str] | None = None,
    last_used_at: str | None = None,
    version_fallback: str | None = None,
) -> dict[str, Any]:
    """Lightweight catalog row for Tools Bibliotheek (no giant schema dump)."""
    meta = definition.normalized_metadata() if hasattr(definition, "normalized_metadata") else dict(
        getattr(definition, "metadata", None) or {}
    )
    cap_id = str(getattr(definition, "id", ""))
    provider_kind = getattr(getattr(definition, "provider_kind", None), "value", getattr(definition, "provider_kind", None))
    in_plugin = bool(plugin_capability_ids and cap_id in plugin_capability_ids)
    origin = resolve_origin(meta, provider_kind=str(provider_kind or ""), in_plugin_bindings=in_plugin)
    cat_key = category_key(meta, capability_id=cap_id)
    available = bool(getattr(definition, "available", True))
    enabled = bool(getattr(definition, "enabled", True))
    if available and enabled:
        status = "active"
        status_label = "Actief"
    elif not enabled:
        status = "inactive"
        status_label = "Inactief"
    else:
        status = "unavailable"
        status_label = "Onbeschikbaar"
    version = tool_version(meta, fallback=version_fallback)
    return {
        "id": cap_id,
        "name": getattr(definition, "name", cap_id),
        "description": getattr(definition, "description", "") or "",
        "provider_kind": provider_kind,
        "provider_ref": getattr(definition, "provider_ref", None),
        "available": available,
        "enabled": enabled,
        "availability_reason": getattr(definition, "availability_reason", None),
        "side_effects": [
            item.value if hasattr(item, "value") else str(item)
            for item in (getattr(definition, "side_effects", ()) or ())
        ],
        "execution_class": definition.execution_class() if hasattr(definition, "execution_class") else None,
        "category": cat_key,
        "category_label": category_label(cat_key),
        "origin": origin,
        "source": origin,
        "source_label": source_label(origin),
        "status": status,
        "status_label": status_label,
        "version": version,
        "last_used_at": last_used_at,
        "tags": list(meta.get("tags") or []),
        "domains": list(meta.get("domains") or []),
        "risk_tier": meta.get("risk_tier"),
        "truth": {
            "active_is_not_authorized": True,
            "registered_is_not_available": True,
            "origin_is_descriptive": True,
        },
    }
