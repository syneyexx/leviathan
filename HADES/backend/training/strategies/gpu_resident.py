"""GPU-resident strategy helpers (closest to current HADES trainer path)."""

from __future__ import annotations

from typing import Any

from training.execution_plan import MemoryStrategy, TrainingExecutionPlan


NAME = MemoryStrategy.GPU_RESIDENT


def apply_model_load_kwargs(plan: TrainingExecutionPlan, base_kwargs: dict[str, Any]) -> dict[str, Any]:
    _ = plan
    kwargs = dict(base_kwargs)
    kwargs.pop("quantization_config", None)
    # Keep device placement to Transformers defaults unless CUDA map is already set.
    return kwargs


def prepare_model(model: Any, plan: TrainingExecutionPlan) -> Any:
    _ = plan
    return model
