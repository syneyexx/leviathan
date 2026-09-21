from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.function_runtime.types import SideEffect


class CapabilityProviderKind(str, Enum):
    FUNCTION = "function"
    KNOWLEDGE = "knowledge"
    ARTIFACT = "artifact"
    INTERNAL = "internal"


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
