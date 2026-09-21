"""Adaptive Training Memory Engine planner."""

from __future__ import annotations

from typing import Any

from training.compatibility import check_strategy_compatibility
from training.estimator import estimate_strategy_memory, vram_reserve_bytes
from training.execution_plan import (
    DEFAULT_STRATEGY_RANK,
    PLANNER_VERSION,
    MemoryStrategy,
    PlanRequest,
    PlanResponse,
    TrainingExecutionPlan,
    confidence_rank,
)
from training.failure_codes import TrainingFailureCode
from training.hardware_probe import HardwareSnapshot, collect_hardware_snapshot
from training.model_inspector import ModelProfile, inspect_model_reference


def _bottleneck_for(strategy: MemoryStrategy) -> str:
    return {
        MemoryStrategy.GPU_RESIDENT: "gpu_compute",
        MemoryStrategy.GPU_RESIDENT_4BIT: "gpu_compute",
        MemoryStrategy.CPU_OFFLOAD: "pcie_transfer",
        MemoryStrategy.RAM_LAYER_STREAMING: "pcie_transfer",
        MemoryStrategy.NVME_LAYER_STREAMING: "storage_read",
    }.get(strategy, "unknown")


def _residency_for(strategy: MemoryStrategy) -> tuple[str, str, str]:
    if strategy == MemoryStrategy.GPU_RESIDENT:
        return "gpu", "gpu", "gpu"
    if strategy == MemoryStrategy.GPU_RESIDENT_4BIT:
        return "gpu", "gpu", "gpu"
    if strategy == MemoryStrategy.CPU_OFFLOAD:
        return "mixed", "gpu", "gpu"
    if strategy == MemoryStrategy.RAM_LAYER_STREAMING:
        return "system_ram", "gpu", "gpu"
    if strategy == MemoryStrategy.NVME_LAYER_STREAMING:
        return "nvme", "gpu", "gpu"
    return "unknown", "unknown", "unknown"


def _precision_for(strategy: MemoryStrategy) -> str:
    if strategy == MemoryStrategy.GPU_RESIDENT_4BIT:
        return "nf4"
    return "auto"


def _buffer_count(request: PlanRequest, strategy: MemoryStrategy) -> int:
    if request.stream_buffer_count == "auto":
        if strategy in {MemoryStrategy.RAM_LAYER_STREAMING, MemoryStrategy.NVME_LAYER_STREAMING}:
            return 2
        return 1
    return max(1, min(int(request.stream_buffer_count), 4))


def _legacy_strategy(request: PlanRequest) -> MemoryStrategy | None:
    """Map legacy load_in_4bit checkbox when memory_strategy is auto."""

    if request.memory_strategy != MemoryStrategy.AUTO:
        return None
    if request.load_in_4bit is True:
        return MemoryStrategy.GPU_RESIDENT_4BIT
    if request.load_in_4bit is False:
        # Explicit false does not force gpu_resident; auto may still choose.
        return None
    return None


def _fits_vram(
    estimate_vram: int,
    reserve: int,
    hardware: HardwareSnapshot,
    *,
    model_weight_known: bool,
    strategy: MemoryStrategy,
) -> tuple[bool, str | None, str | None]:
    total = hardware.gpu.total_vram_bytes.value
    free = hardware.gpu.free_vram_bytes.value
    budget = None
    if isinstance(free, int) and free > 0:
        budget = free
    elif isinstance(total, int) and total > 0:
        budget = total
    if budget is None:
        # Without VRAM facts we cannot prove fit; leave feasible only for non-CUDA hosts.
        if not hardware.gpu.cuda_available.value:
            return True, None, None
        return False, "VRAM capacity unknown; refusing automatic GPU allocation", TrainingFailureCode.INSUFFICIENT_VRAM
    if not model_weight_known and strategy in {
        MemoryStrategy.GPU_RESIDENT,
        MemoryStrategy.GPU_RESIDENT_4BIT,
        MemoryStrategy.CPU_OFFLOAD,
    }:
        # Do not reject framework-managed resident paths solely on provisional estimates.
        return True, None, None
    if estimate_vram + reserve > int(budget):
        return (
            False,
            f"Estimated VRAM peak {estimate_vram} + reserve {reserve} exceeds budget {budget}",
            TrainingFailureCode.INSUFFICIENT_VRAM,
        )
    return True, None, None


def _fits_ram(estimate_ram: int, hardware: HardwareSnapshot, host_limit: int | None) -> tuple[bool, str | None, str | None]:
    available = hardware.host.available_ram_bytes.value
    total = hardware.host.total_ram_bytes.value
    limit = host_limit
    if limit is None:
        if isinstance(available, int) and available > 0:
            limit = int(available * 0.85)
        elif isinstance(total, int) and total > 0:
            limit = int(total * 0.70)
    if limit is None:
        return True, None, None
    if estimate_ram > int(limit):
        return False, f"Estimated RAM peak {estimate_ram} exceeds host limit {limit}", TrainingFailureCode.INSUFFICIENT_RAM
    return True, None, None


def build_candidate_plan(
    strategy: MemoryStrategy,
    *,
    request: PlanRequest,
    hardware: HardwareSnapshot,
    model: ModelProfile,
) -> TrainingExecutionPlan:
    compat = check_strategy_compatibility(
        strategy,
        hardware=hardware,
        model=model,
        experimental_streaming_allowed=request.experimental_streaming_allowed,
    )
    buffer_count = _buffer_count(request, strategy)
    estimate = estimate_strategy_memory(
        strategy=strategy,
        hardware=hardware,
        model=model,
        sequence_length=request.sequence_length,
        batch_size=request.batch_size,
        gradient_accumulation_steps=request.gradient_accumulation_steps,
        lora_r=request.lora_r,
        vram_reserve_override=request.vram_reserve_bytes,
        host_memory_limit_bytes=request.host_memory_limit_bytes,
        buffer_count=buffer_count,
    )
    base_res, train_res, opt_res = _residency_for(strategy)
    activation = request.activation_checkpointing
    if activation == "auto" and strategy in {
        MemoryStrategy.RAM_LAYER_STREAMING,
        MemoryStrategy.NVME_LAYER_STREAMING,
        MemoryStrategy.CPU_OFFLOAD,
    }:
        activation = "enabled"

    plan = TrainingExecutionPlan(
        strategy=strategy,
        precision=_precision_for(strategy),  # type: ignore[arg-type]
        base_model_residency=base_res,  # type: ignore[arg-type]
        trainable_residency=train_res,  # type: ignore[arg-type]
        optimizer_residency=opt_res,  # type: ignore[arg-type]
        activation_checkpointing=activation,
        buffer_count=buffer_count,
        estimated_vram_peak_bytes=estimate.vram_peak_bytes,
        estimated_ram_peak_bytes=estimate.ram_peak_bytes,
        estimated_storage_bytes=estimate.storage_bytes,
        estimated_storage_read_bytes_per_step=estimate.storage_read_bytes_per_step,
        safety_margin_vram_bytes=estimate.safety_margin_vram_bytes,
        expected_bottleneck=_bottleneck_for(strategy),  # type: ignore[arg-type]
        confidence=estimate.confidence,
        warnings=list(estimate.warnings),
        planner_version=PLANNER_VERSION,
        model_profile_hash=model.profile_hash,
        hardware_profile_hash=hardware.profile_hash,
        estimate_sources={
            "vram": "estimated",
            "ram": "estimated",
            "storage": "estimated" if estimate.storage_bytes else "unknown",
        },
    )

    if not compat.compatible:
        plan.feasible = False
        plan.rejection_reason = compat.reason
        plan.failure_code = compat.failure_code
        return plan

    ok_vram, vram_reason, vram_code = _fits_vram(
        estimate.vram_peak_bytes,
        estimate.safety_margin_vram_bytes,
        hardware,
        model_weight_known=bool(model.estimated_total_weight_bytes),
        strategy=strategy,
    )
    if not ok_vram:
        plan.feasible = False
        plan.rejection_reason = vram_reason
        plan.failure_code = vram_code
        return plan

    ok_ram, ram_reason, ram_code = _fits_ram(
        estimate.ram_peak_bytes,
        hardware,
        request.host_memory_limit_bytes,
    )
    if not ok_ram:
        plan.feasible = False
        plan.rejection_reason = ram_reason
        plan.failure_code = ram_code
        return plan

    if strategy == MemoryStrategy.NVME_LAYER_STREAMING and hardware.storage:
        free = hardware.storage[0].free_bytes.value
        if isinstance(free, int) and estimate.storage_bytes and free < estimate.storage_bytes:
            plan.feasible = False
            plan.rejection_reason = "Insufficient free storage for NVMe-backed model staging"
            plan.failure_code = TrainingFailureCode.INSUFFICIENT_STORAGE
            return plan

    plan.feasible = True
    return plan


def select_plan(
    candidates: list[TrainingExecutionPlan],
    *,
    requested: MemoryStrategy,
    experimental_streaming_allowed: bool,
    legacy_force: MemoryStrategy | None = None,
) -> TrainingExecutionPlan | None:
    feasible = [plan for plan in candidates if plan.feasible]
    if requested != MemoryStrategy.AUTO:
        for plan in candidates:
            if plan.strategy == requested:
                if plan.feasible and plan.confidence == "low" and not experimental_streaming_allowed:
                    plan.feasible = False
                    plan.rejection_reason = "low-confidence plan requires experimental_streaming_allowed"
                    plan.failure_code = TrainingFailureCode.LOW_CONFIDENCE_PLAN
                    return plan
                return plan
        return None

    if legacy_force is not None:
        for plan in candidates:
            if plan.strategy == legacy_force:
                return plan if plan.feasible else plan

    # Auto: never silently select low confidence.
    ranked = [
        plan
        for plan in feasible
        if confidence_rank(plan.confidence) >= confidence_rank("medium")
    ]
    rank_index = {strategy: index for index, strategy in enumerate(DEFAULT_STRATEGY_RANK)}
    ranked.sort(key=lambda plan: rank_index.get(plan.strategy, 999))
    if ranked:
        selected = ranked[0]
        selected.selection_reason = "fastest_validated_feasible_strategy"
        return selected
    return None


def plan_training(
    request: PlanRequest,
    *,
    hardware: HardwareSnapshot | None = None,
    model: ModelProfile | None = None,
    storage_paths: list[str] | None = None,
) -> PlanResponse:
    hardware = hardware or collect_hardware_snapshot(storage_paths=storage_paths)
    model = model or inspect_model_reference(request.base_model)
    strategies = [item for item in DEFAULT_STRATEGY_RANK]
    candidates = [
        build_candidate_plan(strategy, request=request, hardware=hardware, model=model)
        for strategy in strategies
    ]
    legacy = _legacy_strategy(request)
    selected = select_plan(
        candidates,
        requested=request.memory_strategy,
        experimental_streaming_allowed=request.experimental_streaming_allowed,
        legacy_force=legacy,
    )
    if selected and selected.feasible and not selected.selection_reason:
        if request.memory_strategy != MemoryStrategy.AUTO:
            selected.selection_reason = "user_requested_strategy"
        elif legacy is not None and selected.strategy == legacy:
            selected.selection_reason = "legacy_load_in_4bit_mapping"
    return PlanResponse(
        selected=selected if selected and selected.feasible else selected,
        candidates=candidates,
        hardware_profile_hash=hardware.profile_hash,
        model_profile_hash=model.profile_hash,
        planner_version=PLANNER_VERSION,
    )


def plan_to_job_fields(plan: TrainingExecutionPlan | None, request: PlanRequest) -> dict[str, Any]:
    """Fields to persist on job.json (never includes secrets)."""

    return {
        "requested_memory_strategy": request.memory_strategy.value,
        "resolved_execution_plan": plan.to_public_dict() if plan else None,
        "planner_version": PLANNER_VERSION,
        "model_profile_hash": plan.model_profile_hash if plan else "",
        "hardware_profile_hash": plan.hardware_profile_hash if plan else "",
        "runtime_peak_vram_bytes": None,
        "runtime_peak_ram_bytes": None,
        "runtime_bytes_host_to_device": None,
        "runtime_observations": [],
        "fallback_history": [],
        "atme_enabled": True,
    }
