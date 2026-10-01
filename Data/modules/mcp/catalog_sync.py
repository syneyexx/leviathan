"""Sync MCP tools/list into CapabilityCatalog + declarative PluginRegistry bindings."""

from __future__ import annotations

import json
from typing import Any

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind
from Data.modules.function_runtime.types import SideEffect
from Data.modules.plugins.registry import PluginRegistry
from Data.modules.plugins.types import AdapterKind, PluginCapabilityBinding, PluginStatus

from .errors import MCP_TOOL_SCHEMA_INVALID, McpError
from .limits import McpLimits
from .policy import resolve_semantic_effects
from .store import McpStore, utc_now
from .types import (
    McpServerConfig,
    McpToolAvailability,
    McpToolRecord,
    mcp_capability_id,
    stable_schema_hash,
)


class McpCatalogSync:
    """Reconcile tools/list into durable McpStore (+ optional in-process catalog).

    Store is the durable source of truth. CapabilityCatalog remains the canonical
    in-process registry and is projected from the store via
    ``project_server_into_catalog`` / ``hydrate_from_store``.
    """

    def __init__(
        self,
        *,
        catalog: CapabilityCatalog | None,
        store: McpStore,
        plugin_registry: PluginRegistry | None = None,
        limits: McpLimits | None = None,
        observability: Any | None = None,
    ) -> None:
        self.catalog = catalog
        self.store = store
        self.plugin_registry = plugin_registry
        self.limits = limits or McpLimits()
        self.observability = observability
        self.schema_change_events: list[dict[str, Any]] = []
        self.sync_issues: list[dict[str, Any]] = []
        self.last_catalog_generation: int = 0

    def sync_tools(
        self,
        config: McpServerConfig,
        tools: list[dict[str, Any]],
        *,
        protocol_version: str | None,
        server_version: str | None,
        available: bool = True,
    ) -> list[McpToolRecord]:
        now = utc_now()
        self.sync_issues = []
        records: list[McpToolRecord] = []
        for raw in tools:
            try:
                record = self._normalize_tool(
                    config,
                    raw,
                    protocol_version=protocol_version,
                    server_version=server_version,
                    available=available,
                    now=now,
                )
            except McpError as exc:
                # Structured issue — do not poison valid siblings.
                tool_name = ""
                if isinstance(raw, dict):
                    tool_name = str(raw.get("name") or "").strip()
                issue = {
                    "tool_name": tool_name or None,
                    "error_code": exc.code,
                    "message": exc.message,
                    "degraded": True,
                    "server_id": config.server_id,
                }
                self.sync_issues.append(issue)
                self._emit_sync_issue(issue)
                continue
            previous = self.store.get_tool(record.capability_id)
            if previous and previous.schema_hash != record.schema_hash:
                event = {
                    "capability_id": record.capability_id,
                    "server_id": config.server_id,
                    "old_hash": previous.schema_hash,
                    "new_hash": record.schema_hash,
                    "at": now,
                }
                self.schema_change_events.append(event)
                self._emit_schema_change(event)
            self.store.upsert_tool(record)
            self._upsert_capability(record, config)
            records.append(record)

        if available:
            # Tools not seen in this list become unavailable (identity preserved).
            seen = {item.capability_id for item in records}
            for existing in self.store.list_tools(server_id=config.server_id):
                if existing.capability_id not in seen and existing.availability == McpToolAvailability.AVAILABLE:
                    updated = McpToolRecord(
                        server_id=existing.server_id,
                        external_name=existing.external_name,
                        capability_id=existing.capability_id,
                        description=existing.description,
                        input_schema=existing.input_schema,
                        schema_hash=existing.schema_hash,
                        semantic_effects=existing.semantic_effects,
                        availability=McpToolAvailability.UNAVAILABLE,
                        first_seen_at=existing.first_seen_at,
                        last_seen_at=now,
                        server_version=existing.server_version,
                        protocol_version=existing.protocol_version,
                    )
                    self.store.upsert_tool(updated)
                    self._upsert_capability(updated, config)

        self._sync_plugin_bindings(config, records)
        generation = self.bump_catalog_generation(config.server_id)
        self.store.replace_sync_issues(
            config.server_id,
            self.sync_issues,
            catalog_generation=generation,
        )
        return records

    def bump_catalog_generation(self, server_id: str) -> int:
        generation = self.store.bump_catalog_generation(server_id)
        self.last_catalog_generation = generation
        return generation

    def project_server_into_catalog(self, server_id: str) -> list[McpToolRecord]:
        """Project durable store tools for one server into CapabilityCatalog (+ plugins)."""
        config = self.store.get_server(server_id)
        if config is None:
            return []
        tools = self.store.list_tools(server_id=server_id)
        for tool in tools:
            self._upsert_capability(tool, config)
        available = [t for t in tools if t.availability == McpToolAvailability.AVAILABLE]
        self._sync_plugin_bindings(config, available)
        self.last_catalog_generation = self.store.get_catalog_generation(server_id)
        return tools

    def hydrate_from_store(self, *, server_id: str | None = None) -> int:
        """Rehydrate CapabilityCatalog + PluginRegistry from durable McpStore."""
        if server_id:
            return len(self.project_server_into_catalog(server_id))
        total = 0
        for config in self.store.list_servers():
            total += len(self.project_server_into_catalog(config.server_id))
        return total

    def mark_unavailable(self, config: McpServerConfig) -> None:
        now = utc_now()
        self.store.mark_server_tools_unavailable(config.server_id)
        for tool in self.store.list_tools(server_id=config.server_id):
            updated = McpToolRecord(
                server_id=tool.server_id,
                external_name=tool.external_name,
                capability_id=tool.capability_id,
                description=tool.description,
                input_schema=tool.input_schema,
                schema_hash=tool.schema_hash,
                semantic_effects=tool.semantic_effects,
                availability=McpToolAvailability.UNAVAILABLE,
                first_seen_at=tool.first_seen_at,
                last_seen_at=now,
                server_version=tool.server_version,
                protocol_version=tool.protocol_version,
            )
            self._upsert_capability(updated, config)
        self._sync_plugin_bindings(config, [])

    def _normalize_tool(
        self,
        config: McpServerConfig,
        raw: dict[str, Any],
        *,
        protocol_version: str | None,
        server_version: str | None,
        available: bool,
        now: str,
    ) -> McpToolRecord:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise McpError(MCP_TOOL_SCHEMA_INVALID, "Tool missing name")
        description = str(raw.get("description") or "")
        schema = raw.get("inputSchema") or raw.get("input_schema") or {"type": "object", "properties": {}}
        if not isinstance(schema, dict):
            raise McpError(MCP_TOOL_SCHEMA_INVALID, f"Tool {name!r} inputSchema must be object")
        schema_bytes = len(json.dumps(schema, ensure_ascii=False).encode("utf-8"))
        if schema_bytes > self.limits.max_tool_schema_bytes:
            raise McpError(
                "MCP_PROTOCOL_LIMIT_EXCEEDED",
                f"Tool {name!r} schema exceeds limit",
            )
        annotations = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else None
        effects = resolve_semantic_effects(config, name, tool_annotations=annotations)
        capability_id = mcp_capability_id(config.server_id, name)
        return McpToolRecord(
            server_id=config.server_id,
            external_name=name,
            capability_id=capability_id,
            description=description,
            input_schema=schema,
            schema_hash=stable_schema_hash(schema),
            semantic_effects=tuple(e.value for e in effects),
            availability=McpToolAvailability.AVAILABLE if available else McpToolAvailability.UNAVAILABLE,
            first_seen_at=now,
            last_seen_at=now,
            server_version=server_version,
            protocol_version=protocol_version,
        )

    def _upsert_capability(self, record: McpToolRecord, config: McpServerConfig) -> None:
        if self.catalog is None:
            return
        effects = tuple(SideEffect(item) for item in record.semantic_effects)
        definition = CapabilityDefinition(
            id=record.capability_id,
            name=f"{config.display_name}:{record.external_name}",
            description=record.description or f"MCP tool {record.external_name}",
            side_effects=effects or (SideEffect.EXECUTE, SideEffect.EXTERNAL_SIDE_EFFECT),
            provider_kind=CapabilityProviderKind.MCP,
            provider_ref=f"{config.server_id}:{record.external_name}",
            input_schema=record.input_schema,
            output_schema={"type": "object"},
            required_permissions=("mcp.invoke",),
            available=record.availability == McpToolAvailability.AVAILABLE,
            availability_reason=None
            if record.availability == McpToolAvailability.AVAILABLE
            else "server_offline",
            schema_hash=record.schema_hash,
            metadata={
                "server_id": config.server_id,
                "external_name": record.external_name,
                "provider_kind": "MCP",
                "trust": config.trust.value,
            },
        )
        self.catalog.upsert(definition)

    def _sync_plugin_bindings(self, config: McpServerConfig, records: list[McpToolRecord]) -> None:
        if self.plugin_registry is None:
            return
        plugin_id = f"mcp:{config.server_id}"
        if not records:
            # Zero-tool results must clear / disable stale plugin bindings.
            existing = self.plugin_registry.get(plugin_id)
            if existing is not None:
                try:
                    self.plugin_registry.replace_bindings(
                        plugin_id,
                        name=config.display_name,
                        bindings=(),
                        metadata={
                            "server_id": config.server_id,
                            "declarative_only": True,
                            "cleared_zero_tools": True,
                        },
                        status=PluginStatus.DISABLED,
                    )
                except Exception:  # noqa: BLE001 — fall back to unregister
                    self.plugin_registry.unregister(plugin_id)
            return
        bindings = tuple(
            PluginCapabilityBinding(
                external_name=item.external_name,
                capability_id=item.capability_id,
                description=item.description,
            )
            for item in records
        )
        existing = self.plugin_registry.get(plugin_id)
        if existing is None:
            try:
                self.plugin_registry.register(
                    name=config.display_name,
                    kind=AdapterKind.MCP,
                    bindings=bindings,
                    version="mcp",
                    endpoint=f"mcp://{config.server_id}",
                    metadata={
                        "server_id": config.server_id,
                        "source_kind": config.source_kind.value,
                        "declarative_only": True,
                    },
                    enable=config.enabled,
                    plugin_id=plugin_id,
                )
            except ValueError:
                pass
            return
        self.plugin_registry.replace_bindings(
            plugin_id,
            name=config.display_name,
            bindings=bindings,
            metadata={
                "server_id": config.server_id,
                "declarative_only": True,
            },
            status=PluginStatus.ENABLED if config.enabled else PluginStatus.DISABLED,
        )

    def _emit_sync_issue(self, issue: dict[str, Any]) -> None:
        if self.observability is None:
            return
        try:
            self.observability.emit(
                "external_capability",
                "mcp.sync_issue",
                payload=dict(issue),
            )
        except Exception:  # noqa: BLE001
            pass

    def _emit_schema_change(self, event: dict[str, Any]) -> None:
        if self.observability is None:
            return
        try:
            self.observability.emit(
                "external_capability",
                "mcp.schema_change",
                payload=dict(event),
            )
        except Exception:  # noqa: BLE001
            pass
