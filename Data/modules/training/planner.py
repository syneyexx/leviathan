"""Hardware-aware training planner — estimates labeled as estimates."""

from __future__ import annotations

from .config import TrainingConfig
from .types import HardwareSnapshot, TrainingCapabilities, TrainingPlan


def plan_training(
    config: TrainingConfig,
    hardware: HardwareSnapshot,
    capabilities: TrainingCapabilities,
) -> TrainingPlan:
    method = (config.method or "").lower()
    warnings: list[str] = []
    details: dict = {
        "estimated": True,
        "cudaAvailable": hardware.cuda_available,
        "gpuCount": len(hardware.gpus),
    }

    if method == "fixture":
        return TrainingPlan(
            strategy="fixture_cpu",
            reason="Deterministic fixture worker for CI / lifecycle tests",
            effective_batch_size=1,
            train_batch_size=1,
            gradient_accumulation=1,
            max_seq_length=min(config.max_seq_length, 128),
            precision="fp32",
            gradient_checkpointing=False,
            load_in_4bit=False,
            warnings=(),
            estimated=True,
            details={**details, "fixture": True},
        )

    batch = max(1, int(config.train_batch_size))
    accum = max(1, int(config.gradient_accumulation))
    seq = max(8, int(config.max_seq_length))
    precision = config.precision
    grad_ckpt = bool(config.gradient_checkpointing)
    load_4bit = bool(config.load_in_4bit) or method == "qlora"

    if not capabilities.can_run_lora and method in {"lora", "qlora", "sft", "dpo"}:
        warnings.append("Required ML packages missing — planner still emits a blocked-path plan")
        return TrainingPlan(
            strategy="blocked_missing_packages",
            reason="torch/transformers/peft unavailable",
            effective_batch_size=batch * accum,
            train_batch_size=batch,
            gradient_accumulation=accum,
            max_seq_length=seq,
            precision=precision,
            gradient_checkpointing=grad_ckpt,
            load_in_4bit=load_4bit,
            warnings=tuple(warnings),
            estimated=True,
            details=details,
        )

    free_vram = None
    if hardware.gpus:
        free_vram = hardware.gpus[0].free_vram_bytes
        details["freeVramBytes"] = free_vram

    if hardware.cuda_available and hardware.gpus:
        if load_4bit and capabilities.can_run_qlora:
            strategy = "gpu_resident_4bit"
            reason = "CUDA GPU present; QLoRA/4-bit selected for VRAM efficiency"
            precision = "nf4"
            grad_ckpt = True
        elif free_vram is not None and free_vram < 8 * 1024**3:
            strategy = "gpu_resident_conservative"
            reason = "Limited free VRAM — reduced batch and gradient checkpointing"
            batch = 1
            accum = max(accum, 8)
            seq = min(seq, 1024)
            grad_ckpt = True
            precision = "fp16" if hardware.supports_fp16 else "fp32"
            warnings.append("VRAM estimate is conservative and labeled estimated")
        else:
            strategy = "gpu_resident"
            reason = "CUDA GPU present with adequate free VRAM (estimate)"
            if hardware.supports_bf16:
                precision = "bf16"
            elif hardware.supports_fp16:
                precision = "fp16"
    else:
        strategy = "cpu_offload"
        reason = "No CUDA GPU measured — CPU training path (slow; estimate)"
        batch = 1
        accum = max(accum, 4)
        seq = min(seq, 512)
        precision = "fp32"
        load_4bit = False
        grad_ckpt = True
        warnings.append("CPU training is slow; not suitable for large models")

    return TrainingPlan(
        strategy=strategy,
        reason=reason,
        effective_batch_size=batch * accum,
        train_batch_size=batch,
        gradient_accumulation=accum,
        max_seq_length=seq,
        precision=precision,
        gradient_checkpointing=grad_ckpt,
        load_in_4bit=load_4bit,
        warnings=tuple(warnings),
        estimated=True,
        details=details,
    )
