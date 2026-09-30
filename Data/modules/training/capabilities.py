"""Optional ML dependency probing — imports never crash the API process."""

from __future__ import annotations

import importlib
from typing import Any, Callable

from .types import (
    MethodSupport,
    MethodSupportStatus,
    PackageAvailability,
    TrainingCapabilities,
)

_PACKAGES = (
    "torch",
    "transformers",
    "datasets",
    "accelerate",
    "peft",
    "trl",
    "bitsandbytes",
    "flash_attn",
    "safetensors",
    "tokenizers",
    "pyarrow",
)

# Hard requirements per durable production method. ``datasets`` is required by
# the causal-LM trainer data path and by TRL.
METHOD_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "sft": ("torch", "transformers", "datasets", "safetensors"),
    "lora": ("torch", "transformers", "datasets", "safetensors", "peft"),
    "qlora": ("torch", "transformers", "datasets", "safetensors", "peft", "bitsandbytes"),
    "dpo": ("torch", "transformers", "datasets", "safetensors", "peft", "trl"),
}
METHOD_OPTIONAL: dict[str, tuple[str, ...]] = {
    "sft": ("accelerate",),
    "lora": ("accelerate",),
    "qlora": ("accelerate",),
    "dpo": ("accelerate",),
}

PackageProbe = Callable[[str], PackageAvailability]


def _probe_package(name: str) -> PackageAvailability:
    try:
        mod = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 — optional dep probe
        return PackageAvailability(name=name, available=False, import_error=str(exc)[:400])
    version = getattr(mod, "__version__", None)
    if version is not None:
        version = str(version)
    return PackageAvailability(name=name, available=True, version=version)


def _probe_cuda(torch_available: bool) -> bool | None:
    if not torch_available:
        return None
    torch = safe_import("torch")
    if torch is None:
        return None
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def _method_support(
    method: str,
    *,
    ok: Callable[[str], bool],
    cuda_available: bool | None,
) -> MethodSupport:
    requires = METHOD_REQUIREMENTS[method]
    missing = tuple(name for name in requires if not ok(name))
    optional_missing = tuple(name for name in METHOD_OPTIONAL.get(method, ()) if not ok(name))
    if missing:
        return MethodSupport(
            method=method,
            status=MethodSupportStatus.DEPENDENCY_MISSING,
            requires=requires,
            missing=missing,
            optional_missing=optional_missing,
            reasons=(f"Install: {', '.join(missing)}",),
        )
    if method == "qlora" and cuda_available is not True:
        return MethodSupport(
            method=method,
            status=MethodSupportStatus.HARDWARE_BLOCKED,
            requires=requires,
            optional_missing=optional_missing,
            reasons=("QLoRA 4-bit (bitsandbytes) requires a CUDA GPU; torch reports CUDA unavailable",),
        )
    reasons: tuple[str, ...] = ()
    if cuda_available is not True:
        reasons = ("CUDA unavailable — runs on CPU (slow; small models only)",)
    return MethodSupport(
        method=method,
        status=MethodSupportStatus.SUPPORTED,
        requires=requires,
        optional_missing=optional_missing,
        reasons=reasons,
    )


def probe_training_capabilities(
    *,
    package_probe: PackageProbe | None = None,
    cuda_available: bool | None = None,
) -> TrainingCapabilities:
    """Probe optional deps. ``package_probe`` / ``cuda_available`` are test seams."""
    probe = package_probe or _probe_package
    packages = tuple(probe(name) for name in _PACKAGES)
    by_name = {p.name: p for p in packages}

    def ok(name: str) -> bool:
        pkg = by_name.get(name)
        return bool(pkg and pkg.available)

    cuda = cuda_available if cuda_available is not None else _probe_cuda(ok("torch"))

    support = {
        method: _method_support(method, ok=ok, cuda_available=cuda)
        for method in ("sft", "lora", "qlora", "dpo")
    }

    missing_lora = support["lora"].missing
    can_sft = support["sft"].operational
    can_lora = support["lora"].operational
    can_qlora = support["qlora"].operational
    can_dpo = support["dpo"].operational
    # Pure-Python preference micro objective (recipe pref_dpo_v1) — not a durable job.
    can_dpo_micro = True
    can_flash = ok("flash_attn") and cuda is True
    can_8bit_optim = ok("bitsandbytes") and cuda is True

    notes: list[str] = []
    if not can_lora:
        notes.append(
            "LoRA unavailable — install torch, transformers, datasets, safetensors, peft. "
            "Fixture training remains available for CI but is not production-ready."
        )
    if not can_sft:
        notes.append("Full SFT unavailable — install torch, transformers, datasets, safetensors.")
    if support["qlora"].status == MethodSupportStatus.DEPENDENCY_MISSING and can_lora:
        notes.append("QLoRA unavailable — bitsandbytes not installed.")
    elif support["qlora"].status == MethodSupportStatus.HARDWARE_BLOCKED:
        notes.append("QLoRA blocked — 4-bit quantized training requires a CUDA GPU.")
    if can_dpo:
        notes.append("Durable DPO (method=dpo) runs TRL DPOTrainer with a LoRA adapter.")
    else:
        notes.append(
            "Durable DPO (method=dpo) unavailable — requires "
            + ", ".join(METHOD_REQUIREMENTS["dpo"])
            + f" (missing: {', '.join(support['dpo'].missing) or 'none'}). "
            "The pure-Python dpo_micro objective (recipe pref_dpo_v1) is separate "
            "(canRunDpoMicro) and is not a durable HF DPO job."
        )
    if ok("flash_attn") and cuda is not True:
        notes.append("flash_attn installed but CUDA unavailable — flash attention cannot be used.")
    notes.append("Multi-GPU training is not implemented; device strategies: auto, single.")
    notes.append(
        "Reward-model / GRPO / RL trainers are FEATURE_GATED until operational trainers exist "
        "(registered recipe ≠ trained capability)."
    )

    ready = any(support[m].operational for m in ("sft", "lora", "qlora", "dpo"))
    return TrainingCapabilities(
        packages=packages,
        can_run_fixture=True,
        can_run_lora=can_lora,
        can_run_qlora=can_qlora,
        can_run_dpo=can_dpo,
        ready=ready,
        missing_for_lora=missing_lora,
        notes=tuple(notes),
        can_run_reward_model=False,
        can_run_grpo=False,
        can_run_rl=False,
        reward_model_status="FEATURE_GATED",
        grpo_status="FEATURE_GATED",
        rl_status="FEATURE_GATED",
        dpo_hf_status=support["dpo"].status.value,
        can_run_sft=can_sft,
        can_run_dpo_micro=can_dpo_micro,
        can_use_flash_attention=can_flash,
        can_use_8bit_optimizer=can_8bit_optim,
        cuda_available=cuda,
        method_support=support,
        missing_for_sft=support["sft"].missing,
        missing_for_qlora=support["qlora"].missing,
        missing_for_dpo=support["dpo"].missing,
    )


def safe_import(name: str) -> Any | None:
    """Import optional module or return None — never raises for missing deps."""
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return None
