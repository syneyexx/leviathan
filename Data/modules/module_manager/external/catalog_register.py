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
            (SideEffect.READ, SideEffect.WRITE, SideEffect.NETWORK, SideEffect.EXECUTE),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.update",
            "Update External Module",
            "Refresh module source/reference via the canonical install lifecycle.",
            "external.update",
            (SideEffect.READ, SideEffect.WRITE, SideEffect.NETWORK, SideEffect.EXECUTE),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.upgrade",
            "Upgrade External Module",
            "Upgrade to a newer compatible module version via staged install lifecycle.",
            "external.upgrade",
            (SideEffect.READ, SideEffect.WRITE, SideEffect.NETWORK, SideEffect.EXECUTE),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.invoke",
            "Invoke External Module",
            "Invoke an external module operation (CLI/script/process/network) via module_runtime.",
            "external.invoke",
            (SideEffect.READ, SideEffect.EXECUTE, SideEffect.NETWORK),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.start",
            "Start External Module Service",
            "Start PROCESS_SERVICE / MCP module lifecycle via module_runtime.",
            "external.start",
            (SideEffect.EXECUTE, SideEffect.WRITE),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.stop",
            "Stop External Module Service",
            "Stop owned external module process via module_runtime.",
            "external.stop",
            (SideEffect.EXECUTE, SideEffect.WRITE),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.restart",
            "Restart External Module Service",
            "Restart owned external module process via module_runtime.",
            "external.restart",
            (SideEffect.EXECUTE, SideEffect.WRITE),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.module.ensure_ready",
            "Ensure External Module Ready",
            "Ensure installed module process/service is ready via module_runtime.",
            "external.ensure_ready",
            (SideEffect.EXECUTE, SideEffect.READ),
            "EXTERNAL_REQUIRED",
            "module_runtime",
        ),
        (
            "external.knowledge.assimilate",
            "Assimilate External Result",
            "Background Knowledge assimilation via knowledge_prepare (bulk writes via db_commit).",
            "external.assimilate",
            (SideEffect.READ, SideEffect.WRITE),
            "EXTERNAL_REQUIRED",
            "knowledge_prepare",
        ),
        (
            "external.skills.search",
            "Search Skills",
            "Bounded search across installed and catalog skills (metadata only).",
            "external.skills",
            (SideEffect.READ,),
            "INLINE_SAFE",
            "general",
        ),
        (
            "external.skills.load",
            "Load Skill Instructions",
            "On-demand load of a selected skill's instructions (not global prompt injection).",
            "external.skills",
            (SideEffect.READ,),
            "INLINE_SAFE",
            "general",
        ),
    ]
    for cap_id, name, description, ref, effects, execution_class, worker_kind in specs:
        if cap_id in catalog:
            # Keep catalog honest on re-register of control caps after this wave.
            try:
                catalog.upsert(
                    CapabilityDefinition(
                        id=cap_id,
                        name=name,
                        description=description,
                        side_effects=effects,
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
                                "ref": {"type": "string"},
                                "force": {"type": "boolean"},
                                "activate": {"type": "boolean"},
                                "action": {"type": "string"},
                            },
                        },
                        output_schema={"type": "object", "additionalProperties": True},
                        metadata={
                            "execution_class": execution_class,
                            "domain": "external_capability",
                            "worker_kind": worker_kind,
                            "worker_pool": worker_kind,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                pass
            continue
        catalog.register(
            CapabilityDefinition(
                id=cap_id,
                name=name,
                description=description,
                side_effects=effects,
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
                        "ref": {"type": "string"},
                        "force": {"type": "boolean"},
                        "activate": {"type": "boolean"},
                        "action": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "additionalProperties": True},
                metadata={
                    "execution_class": execution_class,
                    "domain": "external_capability",
                    "worker_kind": worker_kind,
                    "worker_pool": worker_kind,
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
        execution_class, worker_kind = _execution_owner(external)
        # Manifest side_effects remain authoritative for ApprovalService.
        # Process/network adapters are EXTERNAL_REQUIRED via worker_kind even when
        # a fixture only declares READ — control caps (install/invoke) already
        # declare EXECUTE/NETWORK/WRITE explicitly.
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
                "execution_class": execution_class,
                "worker_kind": worker_kind,
                "worker_pool": worker_kind,
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


def _execution_owner(external: dict) -> tuple[str, str]:
    """Return (execution_class, worker_kind) for a module adapter."""
    adapter = str(external.get("adapter") or "").upper()
    resource = str(external.get("resource_class") or "").upper()
    if adapter == "MCP":
        return "EXTERNAL_REQUIRED", "mcp_execution"
    if adapter in {"CLI", "SCRIPT_PACKAGE", "PROCESS_SERVICE", "HTTP_OPENAPI"}:
        return "EXTERNAL_REQUIRED", "module_runtime"
    if adapter == "COMPOSITE":
        # Composite may invoke external/heavy children — never inline-bypass.
        return "EXTERNAL_REQUIRED", "module_runtime"
    if adapter in {"SKILL_PACK", "CATALOG_SOURCE"}:
        return "INLINE_SAFE", "general"
    if resource in {
        "CPU_HEAVY",
        "MEMORY_HEAVY",
        "IO_HEAVY",
        "NETWORK_HEAVY",
        "NETWORK_BOUND",
        "BACKGROUND",
        "GPU_SHARED",
        "GPU_EXCLUSIVE",
    }:
        return "EXTERNAL_REQUIRED", "module_runtime"
    return "INLINE_SAFE", "general"


def _execution_class(external: dict) -> str:
    return _execution_owner(external)[0]


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
