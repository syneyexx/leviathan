"""Authoritative settings resolver with scoped inheritance."""

from __future__ import annotations

from typing import Any

from .registry import SettingRegistry
from .types import (
    SCOPE_PRECEDENCE,
    CapabilityDescriptor,
    EffectiveValue,
    ResolveContext,
    SettingScope,
    SettingSource,
)
from .validation import is_unlimited, validate_value


class PolicyResolver:
    """Resolve final configured + effective values from the inheritance chain.

    Precedence (low → high):
      system default → global → project → agent_type → agent → plugin → session → task
    External capability constraints are applied when computing *effective* values
    and are never silently applied without marking ``clamped``.
    """

    def __init__(
        self,
        registry: SettingRegistry,
        *,
        global_values: dict[str, Any] | None = None,
        overrides: list[dict[str, Any]] | None = None,
        capabilities: dict[str, CapabilityDescriptor] | None = None,
    ) -> None:
        self.registry = registry
        self.global_values = dict(global_values or {})
        self.overrides = list(overrides or [])
        self.capabilities = dict(capabilities or {})

    def refresh(
        self,
        *,
        global_values: dict[str, Any] | None = None,
        overrides: list[dict[str, Any]] | None = None,
        capabilities: dict[str, CapabilityDescriptor] | None = None,
    ) -> None:
        if global_values is not None:
            self.global_values = dict(global_values)
        if overrides is not None:
            self.overrides = list(overrides)
        if capabilities is not None:
            self.capabilities = dict(capabilities)

    def _matches_context(self, row: dict[str, Any], context: ResolveContext) -> bool:
        scope = str(row.get("scope", ""))
        scope_id = row.get("scope_id")
        mapping = {
            SettingScope.PROJECT.value: context.project_id,
            SettingScope.AGENT_TYPE.value: context.agent_type,
            SettingScope.AGENT.value: context.agent_id,
            SettingScope.PLUGIN.value: context.plugin_id,
            SettingScope.SESSION.value: context.session_id,
            SettingScope.TASK.value: context.task_id,
        }
        if scope in {SettingScope.SYSTEM.value, SettingScope.GLOBAL.value}:
            return True
        expected = mapping.get(scope)
        return bool(expected) and expected == scope_id

    def _layer_value(self, definition_storage_key: str, scope: SettingScope, context: ResolveContext) -> Any | object:
        missing = object()
        if scope == SettingScope.SYSTEM:
            definition = self.registry.require(definition_storage_key) if definition_storage_key in self.registry.storage_keys() else self.registry.require(
                next(d.id for d in self.registry.all() if d.storage_key == definition_storage_key)
            )
            return definition.default_value
        if scope == SettingScope.GLOBAL:
            if definition_storage_key in self.global_values:
                return self.global_values[definition_storage_key]
            return missing
        for row in self.overrides:
            if row.get("key") != definition_storage_key:
                continue
            if str(row.get("scope")) != scope.value:
                continue
            if not self._matches_context(row, context):
                continue
            return row.get("value")
        return missing

    def resolve(self, setting_id: str, context: ResolveContext | None = None) -> EffectiveValue:
        context = context or ResolveContext()
        definition = self.registry.require(setting_id)
        key = definition.storage_key
        inheritance: list[dict[str, Any]] = []
        configured: Any = definition.default_value
        source = SettingSource.SYSTEM_DEFAULT
        scope = SettingScope.SYSTEM

        for layer in SCOPE_PRECEDENCE:
            if layer not in definition.scopes and layer not in {SettingScope.SYSTEM, SettingScope.GLOBAL}:
                # Always allow system+global; other scopes only if declared.
                if layer not in definition.scopes:
                    continue
            missing = object()
            if layer == SettingScope.SYSTEM:
                value = definition.default_value
                inheritance.append({"scope": layer.value, "value": value, "source": SettingSource.SYSTEM_DEFAULT.value})
                configured = value
                source = SettingSource.SYSTEM_DEFAULT
                scope = layer
                continue
            if layer == SettingScope.GLOBAL:
                if key in self.global_values:
                    value = self.global_values[key]
                    # Treat stored default-equal still as global_user if present in DB;
                    # resolver cares about explicit override rows + global map.
                    inheritance.append({"scope": layer.value, "value": value, "source": SettingSource.GLOBAL_USER.value})
                    configured = value
                    source = SettingSource.GLOBAL_USER
                    scope = layer
                continue

            value = missing
            for row in self.overrides:
                if row.get("key") != key:
                    continue
                if str(row.get("scope")) != layer.value:
                    continue
                if not self._matches_context(row, context):
                    continue
                value = row.get("value")
            if value is missing:
                continue
            inheritance.append({"scope": layer.value, "value": value, "source": layer.value})
            configured = value
            source = SettingSource(layer.value) if layer.value in SettingSource._value2member_map_ else SettingSource.GLOBAL_USER
            scope = layer

        configured = validate_value(definition, configured)
        effective = configured
        clamped = False
        clamp_reason = None
        capability_max = None
        unlimited_requested = is_unlimited(configured)

        # Capability clamping (external / runtime)
        cap = self.capabilities.get(definition.id) or self.capabilities.get(key)
        if cap is not None:
            capability_max = cap.provider_max if cap.provider_max is not None else cap.runtime_max
            if capability_max is not None and effective is not None:
                try:
                    if int(effective) > int(capability_max):
                        effective = int(capability_max)
                        clamped = True
                        clamp_reason = f"{cap.kind.value}: {cap.label}"
                        source = (
                            SettingSource.PROVIDER_CAPABILITY
                            if cap.provider_max is not None
                            else SettingSource.RUNTIME_CAPABILITY
                        )
                except (TypeError, ValueError):
                    pass
            elif capability_max is not None and unlimited_requested:
                effective = int(capability_max)
                clamped = True
                clamp_reason = f"{cap.kind.value}: {cap.label} (unlimited requested)"
                source = (
                    SettingSource.PROVIDER_CAPABILITY
                    if cap.provider_max is not None
                    else SettingSource.RUNTIME_CAPABILITY
                )

        return EffectiveValue(
            setting_id=definition.id,
            configured=configured,
            effective=effective,
            source=source,
            scope=scope,
            overrideable=definition.overrideable,
            clamped=clamped,
            clamp_reason=clamp_reason,
            capability_max=capability_max,
            unlimited_requested=unlimited_requested,
            inheritance=inheritance,
        )

    def get(self, setting_id: str, context: ResolveContext | None = None, default: Any = None) -> Any:
        try:
            return self.resolve(setting_id, context).effective
        except KeyError:
            return default

    def snapshot(self, context: ResolveContext | None = None) -> dict[str, Any]:
        context = context or ResolveContext()
        return {d.storage_key: self.resolve(d.id, context).effective for d in self.registry.all()}
