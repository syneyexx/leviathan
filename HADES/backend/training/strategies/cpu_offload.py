"""Framework-native CPU offload strategy helpers."""

from __future__ import annotations

from typing import Any

from training.execution_plan import MemoryStrategy, TrainingExecutionPlan


NAME = MemoryStrategy.CPU_OFFLOAD


def apply_model_load_kwargs(plan: TrainingExecutionPlan, base_kwargs: dict[str, Any]) -> dict[str, Any]:
    kwargs = dict(base_kwargs)
    # Prefer Accelerate/Transformers device_map offload when CUDA exists.
    kwargs["device_map"] = "auto"
    max_memory = kwargs.get("max_memory")
    if max_memory is None:
        # Leave room on GPU; exact bytes come from the plan estimate.
        reserve_gb = max(1, int(plan.safety_margin_vram_bytes // (1024**3)) or 1)
        kwargs["max_memory"] = {0: f"{max(1, (plan.estimated_vram_peak_bytes // (1024**3)) or 2)}GiB", "cpu": "64GiB"}
        kwargs.setdefault("offload_folder", "offload")
        _ = reserve_gb
    return kwargs


def prepare_model(model: Any, plan: TrainingExecutionPlan) -> Any:
    _ = plan
    return model
