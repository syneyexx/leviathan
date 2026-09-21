from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LifecycleMode(str, Enum):
    PURE = "PURE"
    ON_DEMAND = "ON_DEMAND"
    WARM_CACHE = "WARM_CACHE"
    PERSISTENT = "PERSISTENT"


class SideEffect(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    NETWORK = "NETWORK"
    EXECUTE = "EXECUTE"
    DELETE = "DELETE"
    DESTRUCTIVE = "DESTRUCTIVE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


class FunctionCallStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class FunctionDefinition:
    id: str
    name: str
    version: str
    description: str
    entrypoint: str  # import path: package.module:callable
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    lifecycle_mode: LifecycleMode = LifecycleMode.ON_DEMAND
    side_effects: tuple[SideEffect, ...] = (SideEffect.READ,)
    required_permissions: tuple[str, ...] = ()
    network_requirement: bool = False
    filesystem_requirement: bool = False
    cpu_expectation: str = "low"
    ram_expectation_mb: int = 64
    gpu_requirement: bool = False
    vram_expectation_mb: int = 0
    timeout_seconds: float = 30.0
    concurrency_policy: str = "bounded"
    deterministic: bool = True
    cacheable: bool = False
    warmup_cost: str = "cold"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "lifecycle_mode": self.lifecycle_mode.value,
            "side_effects": [item.value for item in self.side_effects],
            "required_permissions": list(self.required_permissions),
            "network_requirement": self.network_requirement,
            "filesystem_requirement": self.filesystem_requirement,
            "cpu_expectation": self.cpu_expectation,
            "ram_expectation_mb": self.ram_expectation_mb,
            "gpu_requirement": self.gpu_requirement,
            "vram_expectation_mb": self.vram_expectation_mb,
            "timeout_seconds": self.timeout_seconds,
            "concurrency_policy": self.concurrency_policy,
            "deterministic": self.deterministic,
            "cacheable": self.cacheable,
            "warmup_cost": self.warmup_cost,
        }


@dataclass
class FunctionResult:
    call_id: str
    function_id: str
    status: FunctionCallStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0
    telemetry: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "function_id": self.function_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "telemetry": self.telemetry,
        }
