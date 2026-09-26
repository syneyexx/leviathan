"""Optional ML dependency probing — imports never crash the API process."""

from __future__ import annotations

import importlib
from typing import Any

from .types import PackageAvailability, TrainingCapabilities

_PACKAGES = (
    "torch",
    "transformers",
    "datasets",
    "accelerate",
    "peft",
    "bitsandbytes",
    "safetensors",
    "tokenizers",
    "pyarrow",
)


def _probe_package(name: str) -> PackageAvailability:
    try:
        mod = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 — optional dep probe
        return PackageAvailability(name=name, available=False, import_error=str(exc)[:400])
    version = getattr(mod, "__version__", None)
    if version is not None:
        version = str(version)
    return PackageAvailability(name=name, available=True, version=version)


def probe_training_capabilities() -> TrainingCapabilities:
    packages = tuple(_probe_package(name) for name in _PACKAGES)
    by_name = {p.name: p for p in packages}

    def ok(name: str) -> bool:
        return bool(by_name[name].available)

    missing_lora = tuple(
        name for name in ("torch", "transformers", "peft", "safetensors") if not ok(name)
    )
    can_lora = len(missing_lora) == 0
    can_qlora = can_lora and ok("bitsandbytes")
    # Round 4: DPO micro objective is always available (pure Python).
    # HF/GPU DPO vertical slice is NOT claimed as production-ready.
    can_dpo = True
    notes: list[str] = []
    if not can_lora:
        notes.append(
            "LoRA/QLoRA unavailable — install torch, transformers, peft, safetensors. "
            "Fixture training remains available for CI."
        )
    if can_lora and not can_qlora:
        notes.append("QLoRA unavailable — bitsandbytes not installed.")
    notes.append(
        "DPO: micro end-to-end objective (dpo_micro / pref_dpo_v1 recipe) is operational for "
        "preference pairs. Durable job method=dpo is blocked (does not silently run LoRA). "
        "HF/GPU production DPO is not claimed."
    )
    notes.append(
        "Reward-model / GRPO / RL trainers are FEATURE_GATED until operational trainers exist "
        "(registered recipe ≠ trained capability)."
    )

    ready = can_lora or True  # fixture always available
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
        dpo_hf_status="FEATURE_GATED",
    )


def safe_import(name: str) -> Any | None:
    """Import optional module or return None — never raises for missing deps."""
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return None
