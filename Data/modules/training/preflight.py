"""Training preflight — PASS / WARNING / BLOCKED with concrete reasons."""

from __future__ import annotations

import os
from pathlib import Path

from Data.modules.common.atomic import ensure_dir

from .capabilities import probe_training_capabilities
from .config import TrainingConfig
from .hardware import probe_hardware
from .store import TrainingStore
from .types import (
    HardwareSnapshot,
    PreflightIssue,
    PreflightResult,
    PreflightVerdict,
    TrainingCapabilities,
)


def run_preflight(
    config: TrainingConfig,
    *,
    store: TrainingStore | None = None,
    hardware: HardwareSnapshot | None = None,
    capabilities: TrainingCapabilities | None = None,
    corpus_root: Path | None = None,
) -> PreflightResult:
    caps = capabilities or probe_training_capabilities()
    hw = hardware or probe_hardware(corpus_path=corpus_root)
    issues: list[PreflightIssue] = []
    details: dict = {
        "method": config.method,
        "cudaAvailable": hw.cuda_available,
        "gpuCount": len(hw.gpus),
    }

    for err in config.validate():
        issues.append(PreflightIssue(severity="error", code="invalid_config", message=err))

    method = (config.method or "").lower()
    fixture_env = os.getenv("LEVIATHAN_TRAINING_FIXTURE", "").strip() in {"1", "true", "yes", "on"}
    is_fixture = method == "fixture" or fixture_env

    if is_fixture:
        details["fixture"] = True
    else:
        if not caps.can_run_lora:
            missing = ", ".join(caps.missing_for_lora) or "unknown"
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="missing_packages",
                    message=f"Required packages missing for {method}: {missing}",
                )
            )
        if method == "qlora" and not caps.can_run_qlora:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="missing_bitsandbytes",
                    message="QLoRA requires bitsandbytes",
                )
            )
        if method in {"lora", "qlora", "sft"} and not hw.cuda_available:
            issues.append(
                PreflightIssue(
                    severity="warning",
                    code="no_cuda",
                    message="CUDA unavailable — training would fall back to CPU (very slow)",
                )
            )
        if config.dataset_version_id and store is not None:
            if not store.dataset_version_exists(config.dataset_version_id):
                issues.append(
                    PreflightIssue(
                        severity="error",
                        code="dataset_missing",
                        message=f"dataset_version_id not found: {config.dataset_version_id}",
                    )
                )
        elif not config.dataset_path and method != "fixture":
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="dataset_required",
                    message="dataset_version_id or dataset_path required",
                )
            )
        if config.dataset_path:
            path = Path(config.dataset_path)
            if not path.exists():
                issues.append(
                    PreflightIssue(
                        severity="error",
                        code="dataset_path_missing",
                        message=f"dataset_path does not exist: {config.dataset_path}",
                    )
                )

        if not (config.base_model_ref or "").strip() or config.base_model_ref == "unspecified":
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="base_model_required",
                    message="base_model_ref must be set for real training",
                )
            )

    # Output writability
    out = config.output_dir
    if out:
        try:
            ensure_dir(Path(out))
            probe = Path(out) / ".leviathan_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="output_not_writable",
                    message=f"output_dir not writable: {exc}",
                )
            )
    elif corpus_root is not None:
        try:
            ensure_dir(corpus_root)
        except OSError as exc:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="corpus_not_writable",
                    message=f"corpus root not writable: {exc}",
                )
            )

    if hw.disk_free_bytes is not None and hw.disk_free_bytes < 100 * 1024 * 1024:
        issues.append(
            PreflightIssue(
                severity="warning",
                code="low_disk",
                message="Less than 100 MiB free disk on training volume (estimate)",
            )
        )

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    if errors:
        verdict = PreflightVerdict.BLOCKED
    elif warnings:
        verdict = PreflightVerdict.WARNING
    else:
        verdict = PreflightVerdict.PASS

    details["issueCount"] = len(issues)
    return PreflightResult(verdict=verdict, issues=tuple(issues), details=details)
