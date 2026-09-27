"""Register external module capabilities into CapabilityCatalog + PluginRegistry."""

from __future__ import annotations

from typing import Any

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect
from Data.modules.plugins.types import AdapterKind, PluginCapabilityBinding, PluginStatus


def register_external_control_capabilities(catalog: CapabilityCatalog) -> None:
    """Control-plane capabilities for install/invoke via JobRuntime / gateway."""
    specs = [
        (
            "external.module.install",
            "Install External Module",
            "Install or refresh an external capability module version (JobRuntime).",
            "external.install",
        ),
        (
            "external.module.invoke",
            "Invoke External Module",
            "Invoke an external module operation (long/heavy work via workers).",
            "external.invoke",
        ),
        (
            "external.knowledge.assimilate",
            "Assimilate External Result",
            "Background knowledge assimilation of an external capability result (provenance retained).",
            "external.assimilate",
        ),
        (
            "external.skills.search",
            "Search Skills",
            "Bounded search across installed and catalog skills (metadata only).",
            "external.skills",
        ),
        (
            "external.skills.load",
            "Load Skill Instructions",
            "On-demand load of a selected skill's instructions (not global prompt injection).",
            "external.skills",
        ),
    ]
    for cap_id, name, description, ref in specs:
        if cap_id in catalog:
            continue
        heavy = cap_id.startswith("external.module.") or cap_id == "external.knowledge.assimilate"
        catalog.register(
            CapabilityDefinition(
                id=cap_id,
                name=name,
                description=description,
                side_effects=(SideEffect.READ, SideEffect.EXECUTE) if heavy else (SideEffect.READ,),
                provider_kind=CapabilityProviderKind.MODULE,
                provider_ref=ref,
                input_schema={
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "module_id": {"type": "string"},
                        "operation": {"type": "string"},
                        "query": {"type": "string"},
                        "skill_id": {"type": "string"},
                        "arguments": {"type": "object"},
                        "mode": {"type": "string"},
                        "capability_id": {"type": "string"},
                        "output": {"type": "object"},
                        "request_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "observation_id": {"type": "string"},
                        "evidence_id": {"type": "string"},
                        "retrieved_at": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "additionalProperties": True},
                metadata={
                    "execution_class": "EXTERNAL_PREFERRED" if heavy else "INLINE_SAFE",
                    "domain": "external_capability",
                },
            )
        )


def register_external_module_capabilities(
    *,
    catalog: CapabilityCatalog,
    plugin_registry: Any,
    managed: Any,
) -> list[str]:
    """Upsert MODULE-kind capabilities from a managed module's announcements."""
    manifest = managed.manifest
    external = (manifest.metadata or {}).get("external")
    if not isinstance(external, dict):
        return []
    registered: list[str] = []
    bindings: list[PluginCapabilityBinding] = []
    side_default = tuple(manifest.side_effects) or ("READ",)
    for announcement in manifest.capabilities:
        cap_id = announcement.capability_id
        effects = []
        for item in announcement.side_effects or side_default:
            try:
                effects.append(SideEffect(str(item).upper()) if not isinstance(item, SideEffect) else item)
            except Exception:  # noqa: BLE001
                effects.append(SideEffect.READ)
        if not effects:
            effects = [SideEffect.READ]
        provider_ref = f"{manifest.module_id}:{announcement.external_name or cap_id.rsplit('.', 1)[-1]}"
        definition = CapabilityDefinition(
            id=cap_id,
            name=announcement.name or cap_id,
            description=announcement.description or f"External capability from {manifest.name}",
            side_effects=tuple(effects),
            provider_kind=CapabilityProviderKind.MODULE,
            provider_ref=provider_ref,
            input_schema={
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "query": {"type": "string"},
                    "topic": {"type": "string"},
                    "target": {"type": "string"},
                    "prompt": {"type": "string"},
                    "brief": {"type": "string"},
                    "session_id": {"type": "string"},
                    "operation": {"type": "string"},
                    "skill_id": {"type": "string"},
                    "name": {"type": "string"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "argv": {"type": "array"},
                    "timeout_seconds": {"type": "number"},
                    "message": {"type": "string"},
                    "symbol": {"type": "string"},
                    "mode": {"type": "string"},
                    "level": {"type": "string"},
                    "stdin": {"type": "string"},
                    "input": {"type": "string"},
                    "force": {"type": "boolean"},
                    "ref": {"type": "string"},
                    "arguments": {"type": "object"},
                    "include_catalog": {"type": "boolean"},
                    "enabled_only": {"type": "boolean"},
                },
            },
            output_schema={"type": "object", "additionalProperties": True},
            required_permissions=tuple(announcement.required_permissions or ()),
            available=True,
            metadata={
                "module_id": manifest.module_id,
                "adapter": external.get("adapter"),
                "domain": external.get("domain"),
                "tags": list(external.get("tags") or []),
                "assimilation_mode": external.get("assimilation_mode") or "NONE",
                "execution_class": _execution_class(external),
                "resource_class": external.get("resource_class"),
                "marketsim_bypass_forbidden": bool(
                    (external.get("metadata") or {}).get("marketsim_bypass_forbidden")
                    or external.get("marketsim_bypass_forbidden")
                ),
                "real_money_blocked": bool(
                    (external.get("metadata") or {}).get("real_money_blocked")
                    or (external.get("metadata") or {}).get("marketsim_bypass_forbidden")
                    or external.get("real_money_blocked")
                ),
                "external_metadata": dict(external.get("metadata") or {}),
            },
        )
        if cap_id in catalog:
            catalog.upsert(definition)
        else:
            catalog.register(definition)
        registered.append(cap_id)
        bindings.append(
            PluginCapabilityBinding(
                external_name=announcement.external_name or cap_id.rsplit(".", 1)[-1],
                capability_id=cap_id,
                description=announcement.description or "",
            )
        )

    if bindings:
        plugin_id = f"external:{manifest.module_id}"
        kind = _plugin_kind(str(external.get("adapter") or "DECLARATIVE"))
        existing = plugin_registry.get(plugin_id)
        if existing is None:
            plugin_registry.register(
                name=manifest.name,
                kind=kind,
                bindings=bindings,
                version=manifest.version,
                metadata={
                    "module_id": manifest.module_id,
                    "adapter": external.get("adapter"),
                    "source": external.get("source") or external.get("source_type"),
                    "durable": True,
                },
                enable=True,
                plugin_id=plugin_id,
            )
        else:
            plugin_registry.replace_bindings(
                plugin_id,
                name=manifest.name,
                bindings=bindings,
                metadata={
                    "module_id": manifest.module_id,
                    "adapter": external.get("adapter"),
                },
                status=PluginStatus.ENABLED,
            )
        if hasattr(plugin_registry, "persist"):
            plugin_registry.persist(plugin_id)
    return registered


def _execution_class(external: dict) -> str:
    adapter = str(external.get("adapter") or "").upper()
    resource = str(external.get("resource_class") or "").upper()
    if resource in {"CPU_HEAVY", "MEMORY_HEAVY", "IO_HEAVY", "NETWORK_HEAVY", "BACKGROUND"}:
        return "EXTERNAL_REQUIRED"
    if adapter in {"CLI", "PROCESS_SERVICE", "SCRIPT_PACKAGE", "COMPOSITE"}:
        return "EXTERNAL_PREFERRED"
    return "INLINE_SAFE"


def _plugin_kind(adapter: str) -> AdapterKind:
    adapter = adapter.upper()
    mapping = {
        "MCP": AdapterKind.MCP,
        "SKILL_PACK": AdapterKind.SKILL,
        "CATALOG_SOURCE": AdapterKind.SKILL,
        "CLI": AdapterKind.DECLARATIVE,
        "SCRIPT_PACKAGE": AdapterKind.DECLARATIVE,
        "PROCESS_SERVICE": AdapterKind.PROTOCOL,
        "HTTP_OPENAPI": AdapterKind.PROTOCOL,
        "COMPOSITE": AdapterKind.DECLARATIVE,
    }
    return mapping.get(adapter, AdapterKind.DECLARATIVE)
