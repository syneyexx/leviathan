"""Strategy compatibility matrix and ranking helpers."""

from __future__ import annotations

from dataclasses import dataclass

from training.execution_plan import MemoryStrategy
from training.failure_codes import TrainingFailureCode
from training.hardware_probe import HardwareSnapshot
from training.model_inspector import ModelProfile


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    reason: str | None = None
    failure_code: str | None = None


def check_strategy_compatibility(
    strategy: MemoryStrategy,
    *,
    hardware: HardwareSnapshot,
    model: ModelProfile,
    experimental_streaming_allowed: bool = False,
    bitsandbytes_required_for_4bit: bool = True,
) -> CompatibilityResult:
    packages = hardware.packages or {}
    cuda = bool(hardware.gpu.cuda_available.value)
    bnb = packages.get("bitsandbytes", {}).get("available")

    if strategy == MemoryStrategy.GPU_RESIDENT:
        if not cuda and (hardware.gpu.total_vram_bytes.value or 0) == 0:
            # CPU-only resident is technically possible for tiny models but uncommon.
            return CompatibilityResult(True, reason="cpu_fallback_resident_allowed")
        return CompatibilityResult(True)

    if strategy == MemoryStrategy.GPU_RESIDENT_4BIT:
        if not cuda:
            return CompatibilityResult(
                False,
                reason="4-bit strategy requires CUDA",
                failure_code=TrainingFailureCode.CUDA_RUNTIME_MISMATCH,
            )
        if bitsandbytes_required_for_4bit and not bnb:
            return CompatibilityResult(
                False,
                reason="bitsandbytes is not available",
                failure_code=TrainingFailureCode.BITSANDBYTES_UNAVAILABLE,
            )
        return CompatibilityResult(True)

    if strategy == MemoryStrategy.CPU_OFFLOAD:
        # Prefer framework-native offload; still needs accelerate/transformers stack at run time.
        return CompatibilityResult(True)

    if strategy == MemoryStrategy.RAM_LAYER_STREAMING:
        if not model.streaming_compatible:
            return CompatibilityResult(
                False,
                reason=model.streaming_compatibility_reason or "architecture_not_allowlisted",
                failure_code=TrainingFailureCode.UNSUPPORTED_ARCHITECTURE,
            )
        return CompatibilityResult(True)

    if strategy == MemoryStrategy.NVME_LAYER_STREAMING:
        if not model.streaming_compatible:
            return CompatibilityResult(
                False,
                reason=model.streaming_compatibility_reason or "architecture_not_allowlisted",
                failure_code=TrainingFailureCode.UNSUPPORTED_ARCHITECTURE,
            )
        if not experimental_streaming_allowed:
            return CompatibilityResult(
                False,
                reason="nvme_layer_streaming requires experimental_streaming_allowed",
                failure_code=TrainingFailureCode.STRATEGY_REJECTED,
            )
        if not cuda:
            return CompatibilityResult(
                False,
                reason="NVMe layer streaming expects a CUDA device for staging buffers",
                failure_code=TrainingFailureCode.CUDA_RUNTIME_MISMATCH,
            )
        return CompatibilityResult(True)

    return CompatibilityResult(False, reason="unknown_strategy", failure_code=TrainingFailureCode.STRATEGY_REJECTED)
