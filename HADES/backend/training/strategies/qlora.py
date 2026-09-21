"""4-bit GPU-resident (QLoRA-style) strategy helpers."""

from __future__ import annotations

from typing import Any

from training.execution_plan import MemoryStrategy, TrainingExecutionPlan


NAME = MemoryStrategy.GPU_RESIDENT_4BIT


def apply_model_load_kwargs(plan: TrainingExecutionPlan, base_kwargs: dict[str, Any], *, torch_module: Any) -> dict[str, Any]:
    from transformers import BitsAndBytesConfig

    kwargs = dict(base_kwargs)
    compute_dtype = (
        torch_module.bfloat16
        if torch_module.cuda.is_available() and torch_module.cuda.is_bf16_supported()
        else torch_module.float16
    )
    kwargs["quantization_config"] = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    kwargs["device_map"] = kwargs.get("device_map") or "auto"
    _ = plan
    return kwargs


def prepare_model(model: Any, plan: TrainingExecutionPlan) -> Any:
    from peft import prepare_model_for_kbit_training

    _ = plan
    return prepare_model_for_kbit_training(model)
