from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class ModuleStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    LOADED = "LOADED"
    INITIALIZED = "INITIALIZED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


class ModuleIsolation(str, Enum):
    INPROC = "INPROC"
    SUBPROCESS = "SUBPROCESS"  # reserved; MVP uses INPROC + crash containment


@dataclass(frozen=True)
class CapabilityAnnouncement:
    capability_id: str
    name: str
    description: str = ""
    external_name: str | None = None
    side_effects: tuple[str, ...] = ("READ",)
    required_permissions: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "external_name": self.external_name,
            "side_effects": list(self.side_effects),
            "required_permissions": list(self.required_permissions),
            "truth": {"discoverable_is_not_authorized": True},
        }


@dataclass(frozen=True)
class ModuleManifest:
    module_id: str
    name: str
    version: str
    entrypoint: str
    capabilities: tuple[CapabilityAnnouncement, ...] = ()
    permissions: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ("READ",)
    isolation: ModuleIsolation = ModuleIsolation.INPROC
    hot_reload: bool = False
    neuro_hooks: tuple[str, ...] = ()
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "capabilities": [item.public_dict() for item in self.capabilities],
            "permissions": list(self.permissions),
            "side_effects": list(self.side_effects),
            "isolation": self.isolation.value,
            "hot_reload": self.hot_reload,
            "neuro_hooks": list(self.neuro_hooks),
            "source_path": self.source_path,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ModuleContext:
    """Initialization context — shared LEVIATHAN services, not a second DI container."""

    database_path: str | None = None
    data_root: str | None = None
    feature_flags: Mapping[str, bool] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleResult:
    module_id: str
    operation: str
    status: str
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "operation": self.operation,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "truth": {
                "module_execute_is_not_gateway_authorize": True,
                "discoverable_is_not_authorized": True,
            },
        }


@dataclass(frozen=True)
class ModuleHealth:
    module_id: str
    status: ModuleStatus
    detail: str = "ok"
    telemetry: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "status": self.status.value,
            "detail": self.detail,
            "telemetry": self.telemetry,
        }


@runtime_checkable
class ILeviathanModule(Protocol):
    """Strict module interface — Universal Module Manager only loader path."""

    @property
    def manifest(self) -> ModuleManifest: ...

    def initialize(self, ctx: ModuleContext) -> None: ...

    def execute(self, operation: str, arguments: Mapping[str, Any]) -> ModuleResult: ...

    def shutdown(self) -> None: ...

    def health(self) -> ModuleHealth: ...
