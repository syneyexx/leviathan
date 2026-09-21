"""ATME telemetry types and safe serialization.

Telemetry must never contain raw training records, secrets, HF tokens, or hidden
reasoning content.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

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

_SECRET_KEY_RE = re.compile(r"(token|secret|password|authorization|api[_-]?key|hf_token)", re.I)
_HIDDEN_KEYS = frozenset(
    {
        "reasoning",
        "chain_of_thought",
        "chain-of-thought",
        "cot",
        "thought",
        "thoughts",
        "scratchpad",
        "internal_reasoning",
        "analysis",
        "text",
        "messages",
        "prompt",
        "completion",
        "content",
    }
)


class TelemetrySample(BaseModel):
    ts: str
    strategy: str | None = None
    step: int | None = None
    max_steps: int | None = None
    loss: float | None = None
    learning_rate: float | None = None
    examples_processed: int | None = None
    tokens_processed: int | None = None
    tokens_per_sec: float | None = None
    step_duration_ms: float | None = None
    eta_seconds: float | None = None
    observed_bottleneck: Bottleneck = "unknown"
    gpu_utilization_percent: float | None = None
    vram_allocated_bytes: int | None = None
    vram_reserved_bytes: int | None = None
    vram_free_bytes: int | None = None
    vram_total_bytes: int | None = None
    current_compute_layer: int | None = None
    current_staged_layer: int | None = None
    h2d_bytes_per_sec: float | None = None
    d2h_bytes_per_sec: float | None = None
    transfer_queue_depth: int | None = None
    cuda_oom_events: int = 0
    process_ram_bytes: int | None = None
    available_ram_bytes: int | None = None
    pinned_memory_bytes: int | None = None
    cpu_utilization_percent: float | None = None
    storage_read_bytes_per_sec: float | None = None
    storage_cache_hits: int | None = None
    storage_cache_misses: int | None = None
    storage_read_latency_ms: float | None = None
    checkpoint_write_bytes_per_sec: float | None = None
    measured_copy_compute_overlap: bool | None = None
    notes: list[str] = Field(default_factory=list)


def sanitize_telemetry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop secrets and raw record fields from any telemetry-like mapping."""

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if _SECRET_KEY_RE.search(key_text) or key_text.lower() in _HIDDEN_KEYS:
            continue
        if isinstance(value, dict):
            cleaned[key_text] = sanitize_telemetry_payload(value)
        elif isinstance(value, list):
            # Never keep list-of-records shaped content.
            if value and isinstance(value[0], dict):
                continue
            cleaned[key_text] = value
        else:
            cleaned[key_text] = value
    return cleaned


def classify_bottleneck(
    *,
    gpu_util: float | None,
    h2d_bytes_per_sec: float | None,
    storage_read_bytes_per_sec: float | None,
    step_duration_ms: float | None,
    vram_allocated_bytes: int | None,
    vram_total_bytes: int | None,
    strategy: str | None = None,
) -> Bottleneck:
    """Derive an observed bottleneck from measurements when possible."""

    if vram_total_bytes and vram_allocated_bytes and vram_allocated_bytes >= int(vram_total_bytes * 0.95):
        return "gpu_memory"
    if storage_read_bytes_per_sec and storage_read_bytes_per_sec > 0 and (gpu_util or 0) < 40:
        return "storage_read"
    if h2d_bytes_per_sec and h2d_bytes_per_sec > 0 and (gpu_util or 0) < 55:
        return "pcie_transfer"
    if gpu_util is not None and gpu_util >= 70:
        return "gpu_compute"
    if step_duration_ms is None:
        return "unknown"
    # Fallback hint from strategy is allowed only as unknown-preserving soft signal.
    _ = strategy
    return "unknown"
