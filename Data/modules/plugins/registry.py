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

    Configuration may be persisted in CONTROL via ExternalCapabilityStore so
    third-party bindings survive restart. Persisted ENABLED != runtime READY.
    """

    def __init__(self, catalog: CapabilityCatalog) -> None:
        self.catalog = catalog
        self._plugins: dict[str, PluginRecord] = {}
        self._store: Any = None

    def attach_store(self, store: Any) -> None:
        """Attach CONTROL persistence (ExternalCapabilityStore). Not a second loader."""
        self._store = store

    def hydrate_from_store(self) -> int:
        """Reload durable plugin binding configs. Does not imply runtime readiness."""
        if self._store is None:
            return 0
        count = 0
        for row in self._store.list_plugin_bindings():
            plugin_id = row["plugin_id"]
            if plugin_id in self._plugins:
                continue
            bindings = []
            for item in row.get("bindings") or []:
                if not isinstance(item, dict):
                    continue
                cap_id = str(item.get("capability_id") or "")
                if not cap_id or cap_id not in self.catalog:
                    # Capability may be re-registered later by module expand.
                    continue
                bindings.append(
                    PluginCapabilityBinding(
                        external_name=str(item.get("external_name") or ""),
                        capability_id=cap_id,
                        description=str(item.get("description") or ""),
                    )
                )
            if not bindings:
                continue
            try:
                kind = AdapterKind(str(row.get("kind") or "DECLARATIVE"))
            except ValueError:
                kind = AdapterKind.DECLARATIVE
            try:
                status = PluginStatus(str(row.get("status") or "REGISTERED"))
            except ValueError:
                status = PluginStatus.REGISTERED
            # Hydrated ENABLED means desired-enabled, not live-ready.
            self._plugins[plugin_id] = PluginRecord(
                plugin_id=plugin_id,
                name=str(row.get("name") or plugin_id),
                kind=kind,
                status=status,
                version=str(row.get("version") or "0.0.0"),
                bindings=tuple(bindings),
                endpoint=row.get("endpoint"),
                metadata={
                    **dict(row.get("metadata") or {}),
                    "hydrated_from_store": True,
                    "persisted_enabled_is_not_runtime_ready": True,
                },
            )
            count += 1
        return count

    def persist(self, plugin_id: str) -> None:
        if self._store is None:
            return
        item = self._plugins.get(plugin_id)
        if item is None:
            return
        self._store.upsert_plugin_binding(
            {
                "plugin_id": item.plugin_id,
                "name": item.name,
                "kind": item.kind.value,
                "status": item.status.value,
                "version": item.version,
                "bindings": [b.public_dict() for b in item.bindings],
                "endpoint": item.endpoint,
                "metadata": item.metadata,
            }
        )

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
        if (metadata or {}).get("durable"):
            self.persist(record.plugin_id)
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
