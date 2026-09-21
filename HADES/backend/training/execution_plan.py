"""Typed TrainingExecutionPlan schema for ATME.

Plans are estimates. Runtime telemetry remains authoritative.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


PLANNER_VERSION = 1

Confidence = Literal["high", "medium", "low"]
Bottleneck = Literal[
    "gpu_compute",
    "gpu_memory",
    "pcie_transfer",
    "host_memory",
    "storage_read",
    "cpu_preprocessing",
    "dataloader",
    "checkpoint_io",
    "unknown",
]
Residency = Literal["gpu", "system_ram", "nvme", "mixed", "unknown"]
PrecisionMode = Literal["bf16", "fp16", "fp32", "nf4", "auto"]
ActivationCheckpointing = Literal["auto", "enabled", "disabled"]


class MemoryStrategy(StrEnum):
    AUTO = "auto"
    GPU_RESIDENT = "gpu_resident"
    GPU_RESIDENT_4BIT = "gpu_resident_4bit"
    CPU_OFFLOAD = "cpu_offload"
    RAM_LAYER_STREAMING = "ram_layer_streaming"
    NVME_LAYER_STREAMING = "nvme_layer_streaming"


# Fastest → slowest default ranking for auto selection.
DEFAULT_STRATEGY_RANK: tuple[MemoryStrategy, ...] = (
    MemoryStrategy.GPU_RESIDENT,
    MemoryStrategy.GPU_RESIDENT_4BIT,
    MemoryStrategy.CPU_OFFLOAD,
    MemoryStrategy.RAM_LAYER_STREAMING,
    MemoryStrategy.NVME_LAYER_STREAMING,
)


def confidence_rank(value: str) -> int:
    order = {"high": 3, "medium": 2, "low": 1}
    return order.get(str(value or "").lower(), 0)


class TrainingExecutionPlan(BaseModel):
    """Resolved or candidate execution plan for one training configuration."""

    strategy: MemoryStrategy
    precision: PrecisionMode = "auto"
    base_model_residency: Residency = "unknown"
    trainable_residency: Residency = "gpu"
    optimizer_residency: Residency = "gpu"
    activation_checkpointing: ActivationCheckpointing = "auto"
    buffer_count: int = Field(default=1, ge=1, le=4)
    estimated_vram_peak_bytes: int = Field(default=0, ge=0)
    estimated_ram_peak_bytes: int = Field(default=0, ge=0)
    estimated_storage_bytes: int = Field(default=0, ge=0)
    estimated_storage_read_bytes_per_step: int = Field(default=0, ge=0)
    safety_margin_vram_bytes: int = Field(default=0, ge=0)
    expected_bottleneck: Bottleneck = "unknown"
    confidence: Confidence = "low"
    warnings: list[str] = Field(default_factory=list)
    planner_version: int = PLANNER_VERSION
    model_profile_hash: str = ""
    hardware_profile_hash: str = ""
    feasible: bool = False
    rejection_reason: str | None = None
    selection_reason: str | None = None
    failure_code: str | None = None
    estimate_sources: dict[str, Literal["detected", "measured", "estimated", "unknown"]] = Field(
        default_factory=dict
    )

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PlanRequest(BaseModel):
    """Inputs accepted by the planning API (no job launch)."""

    base_model: str = Field(min_length=1, max_length=1000)
    dataset_id: str | None = Field(default=None, max_length=100)
    max_steps: int = Field(default=200, ge=1, le=1_000_000)
    learning_rate: float = Field(default=2e-4, gt=0, le=1)
    sequence_length: int = Field(default=1024, ge=64, le=131_072)
    batch_size: int = Field(default=1, ge=1, le=128)
    gradient_accumulation_steps: int = Field(default=8, ge=1, le=4096)
    lora_r: int = Field(default=16, ge=1, le=1024)
    lora_alpha: int = Field(default=32, ge=1, le=8192)
    lora_dropout: float = Field(default=0.05, ge=0, lt=1)
    memory_strategy: MemoryStrategy = MemoryStrategy.AUTO
    activation_checkpointing: ActivationCheckpointing = "auto"
    host_memory_limit_bytes: int | None = Field(default=None, ge=0)
    vram_reserve_bytes: int | None = Field(default=None, ge=0)
    stream_buffer_count: int | Literal["auto"] = "auto"
    experimental_streaming_allowed: bool = False
    load_in_4bit: bool | None = None  # legacy compatibility hint
    approved_network: bool = False


class PlanResponse(BaseModel):
    selected: TrainingExecutionPlan | None = None
    candidates: list[TrainingExecutionPlan] = Field(default_factory=list)
    hardware_profile_hash: str = ""
    model_profile_hash: str = ""
    planner_version: int = PLANNER_VERSION


def stable_hash(payload: dict[str, Any]) -> str:
    """Deterministic content hash for profile fingerprints (no secrets)."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
