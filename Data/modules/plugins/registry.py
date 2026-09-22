from __future__ import annotations

import uuid
from typing import Any

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect

from .types import AdapterKind, PluginCapabilityBinding, PluginRecord, PluginStatus


class PluginRegistry:
    """Declarative plugin/MCP adapters normalized into CapabilityCatalog.

    Discoverable bindings are not automatically authorized — execution still
    goes through ExecutionGateway + policy/approvals.
    """

    def __init__(self, catalog: CapabilityCatalog) -> None:
        self.catalog = catalog
        self._plugins: dict[str, PluginRecord] = {}

    def list(self) -> list[PluginRecord]:
        return sorted(self._plugins.values(), key=lambda item: item.plugin_id)

    def get(self, plugin_id: str) -> PluginRecord | None:
        return self._plugins.get(plugin_id)

    def register(
        self,
        *,
        name: str,
        kind: AdapterKind,
        bindings: list[PluginCapabilityBinding] | tuple[PluginCapabilityBinding, ...],
        version: str = "0.1.0",
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
        enable: bool = True,
        plugin_id: str | None = None,
    ) -> PluginRecord:
        if not bindings:
            raise ValueError("Plugin requires at least one capability binding")
        for binding in bindings:
            if binding.capability_id not in self.catalog:
                raise KeyError(
                    f"Binding capability not in catalog (register capability first): "
                    f"{binding.capability_id}"
                )
        record = PluginRecord(
            plugin_id=plugin_id or str(uuid.uuid4()),
            name=name,
            kind=kind,
            status=PluginStatus.ENABLED if enable else PluginStatus.REGISTERED,
            version=version,
            bindings=tuple(bindings),
            endpoint=endpoint,
            metadata=metadata or {},
        )
        if record.plugin_id in self._plugins:
            raise ValueError(f"Plugin already registered: {record.plugin_id}")
        self._plugins[record.plugin_id] = record
        return record

    def set_status(self, plugin_id: str, status: PluginStatus) -> PluginRecord:
        item = self._plugins.get(plugin_id)
        if item is None:
            raise KeyError(f"Unknown plugin: {plugin_id}")
        updated = PluginRecord(
            plugin_id=item.plugin_id,
            name=item.name,
            kind=item.kind,
            status=status,
            version=item.version,
            bindings=item.bindings,
            endpoint=item.endpoint,
            metadata=item.metadata,
            error=item.error if status == PluginStatus.ERROR else None,
        )
        self._plugins[plugin_id] = updated
        return updated

    def replace_bindings(
        self,
        plugin_id: str,
        *,
        name: str | None = None,
        bindings: list[PluginCapabilityBinding] | tuple[PluginCapabilityBinding, ...] | None = None,
        metadata: dict[str, Any] | None = None,
        status: PluginStatus | None = None,
    ) -> PluginRecord:
        """Update declarative bindings for an existing plugin record (MCP sync)."""
        item = self._plugins.get(plugin_id)
        if item is None:
            raise KeyError(f"Unknown plugin: {plugin_id}")
        new_bindings = tuple(bindings) if bindings is not None else item.bindings
        for binding in new_bindings:
            if binding.capability_id not in self.catalog:
                raise KeyError(
                    f"Binding capability not in catalog (register capability first): "
                    f"{binding.capability_id}"
                )
        updated = PluginRecord(
            plugin_id=item.plugin_id,
            name=name or item.name,
            kind=item.kind,
            status=status or item.status,
            version=item.version,
            bindings=new_bindings,
            endpoint=item.endpoint,
            metadata={**item.metadata, **(metadata or {})},
            error=item.error if (status or item.status) == PluginStatus.ERROR else None,
        )
        self._plugins[plugin_id] = updated
        return updated

    def unregister(self, plugin_id: str) -> bool:
        return self._plugins.pop(plugin_id, None) is not None

    def resolve_capability(self, plugin_id: str, external_name: str) -> str | None:
        """Map external tool name → capability id if plugin is ENABLED."""
        plugin = self._plugins.get(plugin_id)
        if plugin is None or plugin.status != PluginStatus.ENABLED:
            return None
        for binding in plugin.bindings:
            if binding.external_name == external_name:
                return binding.capability_id
        return None

    def register_echo_mcp_stub(self) -> PluginRecord:
        """Register a local MCP-shaped stub that binds to knowledge.search.

        Does not open network sockets. Honest protocol adapter placeholder.
        """
        if "plugin.echo_search" not in self.catalog:
            self.catalog.register(
                CapabilityDefinition(
                    id="plugin.echo_search",
                    name="Plugin Echo Search",
                    description="Declarative plugin alias for knowledge.search (MCP stub).",
                    side_effects=(SideEffect.READ,),
                    provider_kind=CapabilityProviderKind.KNOWLEDGE,
                    provider_ref="hybrid_search",
                    input_schema={
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                    },
                    output_schema={"type": "object"},
                    required_permissions=("knowledge.read",),
                )
            )
        return self.register(
            name="mcp-echo-stub",
            kind=AdapterKind.MCP,
            version="0.0.1",
            endpoint="local://mcp-echo-stub",
            bindings=(
                PluginCapabilityBinding(
                    external_name="search",
                    capability_id="plugin.echo_search",
                    description="MCP search → knowledge.search alias",
                ),
            ),
            metadata={"network": False, "honest_stub": True},
            enable=True,
            plugin_id="mcp-echo-stub",
        )
