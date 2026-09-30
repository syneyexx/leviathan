"""Hardware-aware training planner — estimates labeled as estimates.

The planner never mutates the operator's config. It reports:

- ``requested_config``: planner-relevant knobs exactly as requested
- ``suggested_config``: what the planner recommends for the selected device
- ``effective_config``: what will run (suggested only when explicitly accepted)
"""

from __future__ import annotations

import math
from typing import Any

from .config import BNB_OPTIMIZERS, TrainingConfig
from .device_resolve import DeviceSelection, select_training_device
from .model_source import ModelSource, estimate_param_count, resolve_model_source
from .types import GpuDeviceInfo, HardwareSnapshot, TrainingCapabilities, TrainingPlan

PLAN_KEYS = (
    "train_batch_size",
    "gradient_accumulation",
    "max_seq_length",
    "precision",
    "gradient_checkpointing",
    "load_in_4bit",
    "optimizer",
    "bnb_4bit_compute_dtype",
    "flash_attention",
)

_GIB = 1024**3
_CUDA_CONTEXT_OVERHEAD = int(0.8 * _GIB)


def _bytes_per_weight(config: TrainingConfig, method: str) -> float:
    if config.uses_4bit or method == "qlora":
        return 0.55
    precision = (config.precision or "fp32").lower()
    if method == "sft":
        # Full fine-tune with fp16 AMP keeps fp32 master weights.
        return 2.0 if precision == "bf16" else 4.0
    return 2.0 if precision in {"fp16", "bf16"} else 4.0


def _optimizer_bytes_per_param(optimizer: str, param_bytes: float) -> float:
    if optimizer in {"adamw_bnb_8bit", "paged_adamw_8bit"}:
        return 2.0
    if optimizer == "sgd":
        return 0.0
    if optimizer == "adafactor":
        return max(0.5, param_bytes * 0.25)
    if optimizer == "paged_adamw_32bit":
        return 8.0
    return 2.0 * param_bytes


def estimate_training_memory(
    config: TrainingConfig,
    *,
    model_config: dict[str, Any] | None,
    param_count: int | None = None,
) -> dict[str, Any]:
    """Rough peak-VRAM estimate. Returns ``{"available": False}`` when unknowable."""
    method = config.normalized_method
    cfg = dict(model_config or {})
    params = param_count if param_count is not None else estimate_param_count(cfg)
    if not params:
        return {"available": False, "estimated": True, "reason": "model config.json unavailable"}
    hidden = int(cfg.get("hidden_size") or cfg.get("n_embd") or cfg.get("d_model") or 0)
    layers = int(cfg.get("num_hidden_layers") or cfg.get("n_layer") or cfg.get("num_layers") or 0)
    heads = int(cfg.get("num_attention_heads") or cfg.get("n_head") or 1)
    vocab = int(cfg.get("vocab_size") or 0)

    weight_bytes = _bytes_per_weight(config, method)
    weights = params * weight_bytes
    if method == "sft":
        trainable = params
        grad_bytes = weight_bytes
        opt_bytes = _optimizer_bytes_per_param(config.optimizer, weight_bytes)
    else:
        targets = max(1, len(config.lora_target_modules or []))
        trainable = max(1, layers * targets * int(config.lora_r) * 2 * max(hidden, 1))
        grad_bytes = 4.0
        opt_bytes = _optimizer_bytes_per_param(config.optimizer, 4.0)
        weights += trainable * 4.0
    gradients = trainable * grad_bytes
    optimizer_state = trainable * opt_bytes

    batch = max(1, int(config.train_batch_size))
    seq = max(8, int(config.max_seq_length))
    if method == "dpo":
        batch *= 2  # chosen + rejected forward passes
    act_bytes = 2.0 if (config.precision or "").lower() in {"fp16", "bf16"} or config.uses_4bit else 4.0
    if hidden and layers:
        if config.gradient_checkpointing:
            activations = layers * 2 * seq * batch * hidden * act_bytes
            activations += seq * batch * hidden * (34 + 5 * heads * seq / max(hidden, 1)) * act_bytes / 2
        else:
            activations = layers * seq * batch * hidden * (34 + 5 * heads * seq / max(hidden, 1)) * act_bytes / 2
    else:
        activations = 0.0
    logits = batch * seq * vocab * 4 * 2 if vocab else 0
    total = weights + gradients + optimizer_state + activations + logits + _CUDA_CONTEXT_OVERHEAD
    return {
        "available": True,
        "estimated": True,
        "paramCount": int(params),
        "trainableParamCount": int(trainable),
        "weightsBytes": int(weights),
        "gradientsBytes": int(gradients),
        "optimizerStateBytes": int(optimizer_state),
        "activationsBytes": int(activations),
        "logitsBytes": int(logits),
        "overheadBytes": _CUDA_CONTEXT_OVERHEAD,
        "totalBytes": int(math.ceil(total)),
        "hostLoadBytes": int(params * (2.0 if weight_bytes < 4 else 4.0)),
        "note": "Rough analytic estimate — not a measurement",
    }


def _requested_knobs(config: TrainingConfig) -> dict[str, Any]:
    data = config.to_dict()
    return {key: data.get(key) for key in PLAN_KEYS}


def _preferred_half(hardware: HardwareSnapshot, device: GpuDeviceInfo | None) -> str:
    bf16 = _device_supports_bf16(hardware, device)
    if bf16:
        return "bf16"
    if hardware.supports_fp16:
        return "fp16"
    return "fp32"


def _device_supports_bf16(hardware: HardwareSnapshot, device: GpuDeviceInfo | None) -> bool | None:
    if device is not None and device.compute_capability:
        try:
            return int(device.compute_capability.split(".", 1)[0]) >= 8
        except ValueError:
            return None
    return hardware.supports_bf16


def _base_plan(
    *,
    strategy: str,
    reason: str,
    effective: dict[str, Any],
    warnings: list[str],
    details: dict[str, Any],
    requested: dict[str, Any],
    suggested: dict[str, Any],
    applied: bool,
    selection: DeviceSelection | None,
    memory: dict[str, Any],
) -> TrainingPlan:
    changes = {
        key: {"requested": requested.get(key), "suggested": suggested.get(key)}
        for key in PLAN_KEYS
        if requested.get(key) != suggested.get(key)
    }
    batch = int(effective["train_batch_size"])
    accum = int(effective["gradient_accumulation"])
    return TrainingPlan(
        strategy=strategy,
        reason=reason,
        effective_batch_size=batch * accum,
        train_batch_size=batch,
        gradient_accumulation=accum,
        max_seq_length=int(effective["max_seq_length"]),
        precision=str(effective["precision"]),
        gradient_checkpointing=bool(effective["gradient_checkpointing"]),
        load_in_4bit=bool(effective["load_in_4bit"]),
        warnings=tuple(warnings),
        estimated=True,
        details=details,
        requested_config=requested,
        suggested_config=suggested,
        effective_config=effective,
        suggested_changes=changes,
        suggestions_applied=applied and bool(changes),
        selected_device=selection.public_dict() if selection is not None else None,
        memory_estimate=memory,
    )


def plan_training(
    config: TrainingConfig,
    hardware: HardwareSnapshot,
    capabilities: TrainingCapabilities,
    *,
    apply_suggestions: bool | None = None,
    model_source: ModelSource | None = None,
) -> TrainingPlan:
    method = config.normalized_method
    apply = bool(config.apply_planner_suggestions if apply_suggestions is None else apply_suggestions)
    warnings: list[str] = []
    details: dict[str, Any] = {
        "estimated": True,
        "cudaAvailable": hardware.cuda_available,
        "gpuCount": len(hardware.gpus),
        "multiGpu": "not_implemented",
        "applySuggestions": apply,
    }
    requested = _requested_knobs(config)
    suggested = dict(requested)

    def finish(strategy: str, reason: str, selection: DeviceSelection | None, memory: dict[str, Any]) -> TrainingPlan:
        effective = dict(suggested if apply else requested)
        if method == "qlora":
            effective["load_in_4bit"] = True
        if selection is not None:
            effective["device_strategy"] = selection.strategy
            effective["selected_stable_device_ids"] = selection.stable_device_ids
            effective["resolved_cuda_ordinals"] = selection.ordinals
        return _base_plan(
            strategy=strategy,
            reason=reason,
            effective=effective,
            warnings=warnings,
            details=details,
            requested=requested,
            suggested=suggested,
            applied=apply,
            selection=selection,
            memory=memory,
        )

    if method == "fixture":
        suggested.update(
            {
                "train_batch_size": 1,
                "gradient_accumulation": 1,
                "max_seq_length": min(int(config.max_seq_length), 128),
                "precision": "fp32",
                "gradient_checkpointing": False,
                "load_in_4bit": False,
            }
        )
        details["fixture"] = True
        return finish("fixture_cpu", "Deterministic fixture worker for CI / lifecycle tests", None, {})

    selection = select_training_device(config, hardware)
    details["deviceSelection"] = selection.reason
    warnings.extend(selection.warnings)

    support = capabilities.method_status(method)
    if support is None or not support.operational:
        status = support.status.value if support is not None else "UNSUPPORTED"
        missing = ", ".join(support.missing) if support is not None else ""
        warnings.append(f"method {method} is {status}" + (f" (missing: {missing})" if missing else ""))
        details["methodStatus"] = status
        return finish(
            "blocked_missing_packages" if status == "DEPENDENCY_MISSING" else "blocked_method_unavailable",
            f"{method} unavailable: {status}",
            selection,
            {},
        )

    if not selection.ok:
        warnings.extend(selection.errors)
        return finish("blocked_device_unavailable", "; ".join(selection.errors), selection, {})

    source = model_source or resolve_model_source(config.base_model_ref, revision=config.base_model_revision)
    details["modelSource"] = source.kind
    device = selection.device
    free_vram = device.free_vram_bytes if device is not None else None
    total_vram = device.total_vram_bytes if device is not None else None
    details["freeVramBytes"] = free_vram
    details["totalVramBytes"] = total_vram

    if config.flash_attention and not capabilities.can_use_flash_attention:
        suggested["flash_attention"] = False
        warnings.append("flash_attention requested but flash_attn/CUDA unavailable — suggest disabling")
    if config.optimizer in BNB_OPTIMIZERS and not capabilities.can_use_8bit_optimizer:
        suggested["optimizer"] = "adamw_torch"
        warnings.append(f"optimizer {config.optimizer} needs bitsandbytes + CUDA — suggest adamw_torch")

    on_gpu = hardware.cuda_available and device is not None
    if on_gpu:
        half = _preferred_half(hardware, device)
        bf16_ok = _device_supports_bf16(hardware, device)
        if (config.precision or "").lower() == "bf16" and bf16_ok is False:
            suggested["precision"] = "fp16"
            warnings.append("bf16 unsupported on selected GPU (compute capability < 8.0) — suggest fp16")
        if config.uses_4bit and bf16_ok is False and config.bnb_4bit_compute_dtype == "bfloat16":
            suggested["bnb_4bit_compute_dtype"] = "float16"
        if config.uses_4bit:
            strategy = "gpu_resident_4bit"
            reason = "Selected CUDA GPU; QLoRA/4-bit for VRAM efficiency"
            suggested["load_in_4bit"] = True
            suggested["gradient_checkpointing"] = True
            if (config.precision or "fp32").lower() in {"fp32", "nf4"}:
                suggested["precision"] = half
        else:
            strategy = "gpu_resident"
            reason = "Selected CUDA GPU with adequate free VRAM (estimate)"
            if (config.precision or "fp32").lower() == "fp32" and half != "fp32":
                suggested["precision"] = half
    else:
        strategy = "cpu_training"
        reason = "No CUDA GPU usable — CPU training path (slow; estimate)"
        suggested["precision"] = "fp32"
        suggested["load_in_4bit"] = False
        suggested["flash_attention"] = False
        warnings.append("CPU training is slow; not suitable for large models")

    memory = estimate_training_memory(
        TrainingConfig.from_dict({**config.to_dict(), **suggested}),
        model_config=source.model_config,
    )
    if on_gpu and memory.get("available") and free_vram is not None and memory["totalBytes"] > free_vram:
        strategy = "gpu_resident_conservative"
        reason = "Estimated VRAM exceeds free VRAM on selected GPU — reduced micro-batch and checkpointing"
        batch = int(config.train_batch_size)
        accum = int(config.gradient_accumulation)
        suggested["train_batch_size"] = 1
        # Preserve effective batch size via accumulation.
        suggested["gradient_accumulation"] = max(accum, batch * accum)
        suggested["gradient_checkpointing"] = True
        suggested["max_seq_length"] = min(int(config.max_seq_length), 1024)
        memory = estimate_training_memory(
            TrainingConfig.from_dict({**config.to_dict(), **suggested}),
            model_config=source.model_config,
        )
        if memory.get("available") and memory["totalBytes"] > free_vram:
            hint = " — consider method=lora or qlora" if method == "sft" else ""
            warnings.append("Estimated VRAM still exceeds free VRAM after conservative settings" + hint)
        else:
            warnings.append("VRAM estimate is conservative and labeled estimated")
    elif on_gpu and free_vram is not None and free_vram < 8 * _GIB and not memory.get("available"):
        strategy = "gpu_resident_conservative"
        reason = "Limited free VRAM and model size unknown — reduced micro-batch and checkpointing"
        suggested["train_batch_size"] = 1
        suggested["gradient_accumulation"] = max(
            int(config.gradient_accumulation), int(config.train_batch_size) * int(config.gradient_accumulation)
        )
        suggested["gradient_checkpointing"] = True
        suggested["max_seq_length"] = min(int(config.max_seq_length), 1024)
        warnings.append("VRAM estimate is conservative and labeled estimated")

    if not apply and any(requested.get(k) != suggested.get(k) for k in PLAN_KEYS):
        warnings.append("Planner suggestions not applied — pass accept_plan or apply_planner_suggestions")
    return finish(strategy, reason, selection, memory)


def apply_plan_to_config(config: TrainingConfig, plan: TrainingPlan) -> TrainingConfig:
    """Return a new config with the planner's suggested knobs (explicit opt-in only)."""
    updates = {key: plan.suggested_config[key] for key in PLAN_KEYS if key in plan.suggested_config}
    return config.with_updates(**updates)
