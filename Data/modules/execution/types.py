from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.function_runtime.types import SideEffect

from .metadata import normalize_capability_metadata, schema_hash

# field is used by CapabilityDefinition.metadata default_factory


class CapabilityProviderKind(str, Enum):
    FUNCTION = "function"
    KNOWLEDGE = "knowledge"
    ARTIFACT = "artifact"
    INTERNAL = "internal"
    MCP = "mcp"
    MODULE = "module"
    EXTERNAL = "external"
    NATIVE = "native"
    BUILTIN = "builtin"
    BROWSER = "browser"
    MEDIA = "media"
    VOICE = "voice"


class CapabilityStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    name: str
    description: str
    side_effects: tuple[SideEffect, ...]
    provider_kind: CapabilityProviderKind
    provider_ref: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permissions: tuple[str, ...] = ()
    available: bool = True
    availability_reason: str | None = None
    enabled: bool = True
    schema_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_metadata(self) -> dict[str, Any]:
        return normalize_capability_metadata(
            self.metadata,
            capability_id=self.id,
            name=self.name,
            description=self.description,
        )

    def resolved_schema_hash(self) -> str:
        return self.schema_hash or schema_hash(self.input_schema, self.output_schema)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "side_effects": [item.value for item in self.side_effects],
            "provider_kind": self.provider_kind.value,
            "provider_ref": self.provider_ref,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "required_permissions": list(self.required_permissions),
            "available": self.available,
            "availability_reason": self.availability_reason,
            "enabled": self.enabled,
            "schema_hash": self.resolved_schema_hash(),
            "metadata": self.normalized_metadata(),
            "truth": {
                "discoverable_is_not_authorized": True,
                "registered_is_not_available": True,
                "available_is_not_enabled": True,
                "enabled_is_not_approved": True,
                "metadata_is_not_authorization": True,
            },
        }


@dataclass(frozen=True)
class CapabilityRequest:
    capability_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    approval_id: str | None = None
    requested_by: str = "api"
    # Wave 0 correlation + idempotency (U006 / U017)
    trace_id: str | None = None
    idempotency_key: str | None = None


@dataclass
class CapabilityResult:
    request_id: str
    capability_id: str
    status: CapabilityStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    side_effects: tuple[SideEffect, ...] = ()
    provider_kind: str | None = None
    provider_ref: str | None = None
    approval_id: str | None = None
    telemetry: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "side_effects": [item.value for item in self.side_effects],
            "provider_kind": self.provider_kind,
            "provider_ref": self.provider_ref,
            "approval_id": self.approval_id,
            "telemetry": self.telemetry,
        }
