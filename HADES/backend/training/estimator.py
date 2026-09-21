"""Conservative memory estimation for ATME planning.

Estimates are labeled with confidence. Sequence length and batch size always
influence activation estimates. Plans never target 100% of free VRAM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from training.execution_plan import MemoryStrategy
from training.hardware_probe import HardwareSnapshot
from training.model_inspector import ModelProfile

Confidence = Literal["high", "medium", "low"]

# Defensible defaults before calibration exists. Absolute floor + percentage of total.
DEFAULT_VRAM_RESERVE_FLOOR_BYTES = 512 * 1024 * 1024
DEFAULT_VRAM_RESERVE_FRACTION = 0.12
DEFAULT_RAM_RESERVE_FRACTION = 0.15
FRAMEWORK_OVERHEAD_BYTES = 512 * 1024 * 1024
CUDA_FRAGMENTATION_FRACTION = 0.08
LORA_BYTES_PER_PARAM = 2  # bf16/fp16 trainable params typical
OPTIMIZER_STATE_MULTIPLIER = 2.0  # AdamW moments approx relative to trainable params
ACTIVATION_BYTES_PER_TOKEN_PER_LAYER = 2  # rough hidden activation footprint factor


@dataclass(frozen=True)
class MemoryEstimate:
    strategy: MemoryStrategy
    vram_peak_bytes: int
    ram_peak_bytes: int
    storage_bytes: int
    storage_read_bytes_per_step: int
    safety_margin_vram_bytes: int
    confidence: Confidence
    components: dict[str, int]
    warnings: list[str]


def vram_reserve_bytes(total_vram: int | None, override: int | None = None) -> int:
    if override is not None and override >= 0:
        return int(override)
    if not total_vram or total_vram <= 0:
        return DEFAULT_VRAM_RESERVE_FLOOR_BYTES
    return max(DEFAULT_VRAM_RESERVE_FLOOR_BYTES, int(total_vram * DEFAULT_VRAM_RESERVE_FRACTION))


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _lora_trainable_params(profile: ModelProfile, lora_r: int) -> int:
    layers = profile.num_hidden_layers or 0
    hidden = profile.hidden_size or 0
    if layers <= 0 or hidden <= 0 or lora_r <= 0:
        # Conservative fallback when architecture unknown.
        base = profile.parameter_count_estimated or 1_000_000_000
        return max(1_000_000, int(base * 0.01))
    # Approximate all-linear LoRA on q/k/v/o + gate/up/down style projections.
    linear_modules_per_layer = 7
    return layers * linear_modules_per_layer * 2 * hidden * int(lora_r)


def _activation_bytes(
    *,
    layers: int,
    hidden: int,
    sequence_length: int,
    batch_size: int,
    resident_layers: int | None = None,
) -> int:
    layers = max(1, layers)
    hidden = max(1, hidden)
    seq = max(1, sequence_length)
    batch = max(1, batch_size)
    active_layers = layers if resident_layers is None else max(1, resident_layers)
    # activations ~ batch * seq * hidden * layers * dtype(+workspace)
    base = batch * seq * hidden * active_layers * ACTIVATION_BYTES_PER_TOKEN_PER_LAYER
    attention_workspace = batch * seq * seq * max(1, active_layers // max(1, layers)) * 2
    return int(base + attention_workspace)


def estimate_strategy_memory(
    *,
    strategy: MemoryStrategy,
    hardware: HardwareSnapshot,
    model: ModelProfile,
    sequence_length: int,
    batch_size: int,
    gradient_accumulation_steps: int,
    lora_r: int,
    vram_reserve_override: int | None = None,
    host_memory_limit_bytes: int | None = None,
    buffer_count: int = 1,
) -> MemoryEstimate:
    warnings: list[str] = []
    total_vram = _int_or_zero(hardware.gpu.total_vram_bytes.value)
    free_vram = _int_or_zero(hardware.gpu.free_vram_bytes.value) or total_vram
    total_ram = _int_or_zero(hardware.host.total_ram_bytes.value)
    available_ram = _int_or_zero(hardware.host.available_ram_bytes.value) or total_ram
    weight_bytes = _int_or_zero(model.estimated_total_weight_bytes) or _int_or_zero(
        (model.parameter_count_estimated or 0) * 2
    )
    bytes_per_layer = _int_or_zero(model.estimated_bytes_per_layer) or max(1, weight_bytes // max(1, model.num_hidden_layers or 32))
    layers = model.num_hidden_layers or 32
    hidden = model.hidden_size or 2048
    lora_params = _lora_trainable_params(model, lora_r)
    lora_bytes = lora_params * LORA_BYTES_PER_PARAM
    lora_grad_bytes = lora_bytes
    optimizer_bytes = int(lora_bytes * OPTIMIZER_STATE_MULTIPLIER)
    dataloader_bytes = batch_size * sequence_length * 8 * 4  # ids/masks rough
    reserve = vram_reserve_bytes(total_vram or None, vram_reserve_override)
    buffer_count = max(1, min(int(buffer_count), 4))

    components: dict[str, int] = {
        "lora_params": lora_bytes,
        "lora_gradients": lora_grad_bytes,
        "optimizer": optimizer_bytes,
        "dataloader": dataloader_bytes,
        "framework_overhead": FRAMEWORK_OVERHEAD_BYTES,
        "safety_reserve_vram": reserve,
    }

    confidence: Confidence = "medium"
    if strategy in {MemoryStrategy.GPU_RESIDENT, MemoryStrategy.GPU_RESIDENT_4BIT, MemoryStrategy.CPU_OFFLOAD}:
        # Resident/offload paths already exist in HADES; unknown Hub metadata is a warning,
        # not an automatic low-confidence block for the framework-managed path.
        if model.sources.get("parameter_count_estimated") == "unknown" or not model.estimated_total_weight_bytes:
            confidence = "medium"
            warnings.append(
                "Model weight size is not fully known locally; VRAM estimate is provisional and runtime allocation remains authoritative."
            )
        elif model.sources.get("parameter_count_estimated") == "detected" and model.local_path:
            confidence = "high"
    else:
        if model.sources.get("parameter_count_estimated") == "unknown" or not model.estimated_total_weight_bytes:
            confidence = "low"
            warnings.append("Model weight size is not fully known; streaming estimates are conservative and low-confidence.")
        elif model.sources.get("parameter_count_estimated") == "detected" and model.local_path:
            confidence = "high"
        else:
            confidence = "medium"

    storage_bytes = 0
    storage_read_per_step = 0
    vram = 0
    ram = 0

    if strategy == MemoryStrategy.GPU_RESIDENT:
        activations = _activation_bytes(layers=layers, hidden=hidden, sequence_length=sequence_length, batch_size=batch_size)
        fragmentation = int((weight_bytes + lora_bytes + optimizer_bytes + activations) * CUDA_FRAGMENTATION_FRACTION)
        components.update(
            {
                "base_weights": weight_bytes,
                "activations": activations,
                "cuda_fragmentation": fragmentation,
            }
        )
        vram = weight_bytes + lora_bytes + lora_grad_bytes + optimizer_bytes + activations + fragmentation + FRAMEWORK_OVERHEAD_BYTES + dataloader_bytes
        ram = int(available_ram * 0.05) + dataloader_bytes + FRAMEWORK_OVERHEAD_BYTES
    elif strategy == MemoryStrategy.GPU_RESIDENT_4BIT:
        quant_weights = max(1, weight_bytes // 4)
        quant_meta = max(1, weight_bytes // 32)
        activations = _activation_bytes(layers=layers, hidden=hidden, sequence_length=sequence_length, batch_size=batch_size)
        fragmentation = int((quant_weights + lora_bytes + optimizer_bytes + activations) * CUDA_FRAGMENTATION_FRACTION)
        components.update(
            {
                "base_weights_4bit": quant_weights,
                "quantization_metadata": quant_meta,
                "activations": activations,
                "cuda_fragmentation": fragmentation,
            }
        )
        vram = quant_weights + quant_meta + lora_bytes + lora_grad_bytes + optimizer_bytes + activations + fragmentation + FRAMEWORK_OVERHEAD_BYTES
        ram = dataloader_bytes + FRAMEWORK_OVERHEAD_BYTES
        if confidence == "high":
            confidence = "medium"
        warnings.append("4-bit path requires bitsandbytes + CUDA; allocator behavior varies by platform.")
    elif strategy == MemoryStrategy.CPU_OFFLOAD:
        # Framework offload keeps some weights on host; GPU holds active slice + trainable.
        staged = max(bytes_per_layer * 2, weight_bytes // 8)
        activations = _activation_bytes(layers=layers, hidden=hidden, sequence_length=sequence_length, batch_size=batch_size)
        components.update({"staged_or_active_weights": staged, "activations": activations, "host_base_weights": weight_bytes})
        vram = staged + lora_bytes + lora_grad_bytes + optimizer_bytes + activations + FRAMEWORK_OVERHEAD_BYTES
        ram = weight_bytes + dataloader_bytes + FRAMEWORK_OVERHEAD_BYTES
        confidence = "medium" if confidence != "low" else "low"
        warnings.append("CPU offload uses framework-native placement; throughput must be measured.")
    elif strategy == MemoryStrategy.RAM_LAYER_STREAMING:
        buffer_bytes = bytes_per_layer * buffer_count
        # Activations with checkpointing tendency: treat as fewer resident layers.
        activations = _activation_bytes(
            layers=layers,
            hidden=hidden,
            sequence_length=sequence_length,
            batch_size=batch_size,
            resident_layers=max(2, min(layers, 4)),
        )
        components.update(
            {
                "gpu_layer_buffers": buffer_bytes,
                "activations": activations,
                "host_base_weights": weight_bytes,
            }
        )
        vram = buffer_bytes + lora_bytes + lora_grad_bytes + optimizer_bytes + activations + FRAMEWORK_OVERHEAD_BYTES
        ram = weight_bytes + dataloader_bytes + FRAMEWORK_OVERHEAD_BYTES + buffer_bytes
        if not model.streaming_compatible:
            confidence = "low"
            warnings.append("Architecture is not on the ATME streaming allowlist.")
        elif confidence != "low":
            confidence = "medium"
        warnings.append("RAM layer streaming is PCIe-bound; do not expect VRAM-equivalent throughput.")
    elif strategy == MemoryStrategy.NVME_LAYER_STREAMING:
        buffer_bytes = bytes_per_layer * buffer_count
        read_ahead = bytes_per_layer * max(2, buffer_count)
        activations = _activation_bytes(
            layers=layers,
            hidden=hidden,
            sequence_length=sequence_length,
            batch_size=batch_size,
            resident_layers=max(2, min(layers, 4)),
        )
        components.update(
            {
                "gpu_layer_buffers": buffer_bytes,
                "ram_read_ahead_cache": read_ahead,
                "activations": activations,
                "host_working_set": read_ahead + FRAMEWORK_OVERHEAD_BYTES,
            }
        )
        vram = buffer_bytes + lora_bytes + lora_grad_bytes + optimizer_bytes + activations + FRAMEWORK_OVERHEAD_BYTES
        ram = read_ahead + dataloader_bytes + FRAMEWORK_OVERHEAD_BYTES + buffer_bytes
        storage_bytes = weight_bytes
        storage_read_per_step = bytes_per_layer * layers * 2  # forward+backward restream approx
        confidence = "low" if not model.streaming_compatible else "medium"
        warnings.append("NVMe streaming is a last resort and is expected to be storage-bound.")
    else:
        raise ValueError(f"Unsupported strategy for estimation: {strategy}")

    # Gradient accumulation does not multiply resident optimizer/activations linearly,
    # but micro-batch workspace can grow slightly; keep a small additive allowance.
    if gradient_accumulation_steps > 1:
        extra = int(dataloader_bytes * min(4, gradient_accumulation_steps) * 0.25)
        components["grad_accum_workspace"] = extra
        vram += extra

    if host_memory_limit_bytes is not None and host_memory_limit_bytes > 0:
        components["host_memory_limit"] = int(host_memory_limit_bytes)

    # Planning budget uses free VRAM when known, else total.
    _ = free_vram  # exposed via hardware; estimator returns peaks for planner comparison.
    if total_ram and ram > int(total_ram * (1.0 - DEFAULT_RAM_RESERVE_FRACTION)):
        warnings.append("Estimated RAM peak approaches system capacity after reserve.")

    return MemoryEstimate(
        strategy=strategy,
        vram_peak_bytes=int(vram),
        ram_peak_bytes=int(ram),
        storage_bytes=int(storage_bytes),
        storage_read_bytes_per_step=int(storage_read_per_step),
        safety_margin_vram_bytes=int(reserve),
        confidence=confidence,
        components=components,
        warnings=warnings,
    )
