"""Training preflight — PASS / WARNING / BLOCKED with concrete reasons."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import ensure_dir

from .capabilities import probe_training_capabilities
from .config import BNB_OPTIMIZERS, TrainingConfig
from .device_resolve import DeviceSelection, select_training_device
from .hardware import probe_hardware
from .model_source import ModelSource, resolve_model_source
from .planner import estimate_training_memory
from .store import TrainingStore
from .types import (
    HardwareSnapshot,
    MethodSupportStatus,
    PreflightIssue,
    PreflightResult,
    PreflightVerdict,
    TrainingCapabilities,
)

_SCHEMA_SAMPLE_ROWS = 64
_MIB = 1024 * 1024


def _dataset_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob("**/*.jsonl")) + sorted(path.glob("**/*.json")) + sorted(path.glob("**/*.txt"))
    return [path]


def sample_dataset_rows(path: Path, *, limit: int = _SCHEMA_SAMPLE_ROWS) -> tuple[list[Any], list[str]]:
    """Read up to ``limit`` JSONL rows (bounded; never the full file)."""
    rows: list[Any] = []
    kinds: list[str] = []
    for file in _dataset_files(path):
        if len(rows) >= limit:
            break
        suffix = file.suffix.lower()
        kinds.append(suffix or "none")
        if suffix == ".txt":
            rows.append({"text": "<txt>"})
            continue
        try:
            with file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        rows.append(None)
                    if len(rows) >= limit:
                        break
        except OSError:
            continue
    return rows, kinds


def check_dataset_schema(method: str, path: Path) -> list[PreflightIssue]:
    rows, _ = sample_dataset_rows(path)
    if not rows:
        return [PreflightIssue("error", "dataset_empty", f"dataset has no readable rows: {path}")]
    dicts = [r for r in rows if isinstance(r, dict)]
    invalid = len(rows) - len(dicts)
    issues: list[PreflightIssue] = []
    if invalid:
        issues.append(
            PreflightIssue("warning", "dataset_rows_unparseable", f"{invalid}/{len(rows)} sampled rows are not JSON objects")
        )
    if method == "dpo":
        def is_pref(row: dict[str, Any]) -> bool:
            chosen = row.get("chosen", row.get("preferred_text"))
            rejected = row.get("rejected", row.get("rejected_text"))
            return bool(chosen) and bool(rejected)

        bad = [r for r in dicts if not is_pref(r)]
        if not dicts or len(bad) == len(dicts):
            issues.append(
                PreflightIssue(
                    "error",
                    "dataset_schema_invalid",
                    "DPO requires preference rows with 'chosen' and 'rejected' (and usually 'prompt')",
                )
            )
        elif bad:
            issues.append(
                PreflightIssue(
                    "warning",
                    "dataset_schema_partial",
                    f"{len(bad)}/{len(dicts)} sampled rows lack chosen/rejected and will be skipped",
                )
            )
        return issues

    def is_sft(row: dict[str, Any]) -> bool:
        if isinstance(row.get("messages"), list) and row["messages"]:
            return True
        return isinstance(row.get("text"), str) and bool(row["text"].strip())

    bad = [r for r in dicts if not is_sft(r)]
    if not dicts or len(bad) == len(dicts):
        issues.append(
            PreflightIssue(
                "error",
                "dataset_schema_invalid",
                f"{method} requires rows with 'text' or chat 'messages'",
            )
        )
    elif bad:
        issues.append(
            PreflightIssue(
                "warning",
                "dataset_schema_partial",
                f"{len(bad)}/{len(dicts)} sampled rows lack text/messages and will be skipped",
            )
        )
    return issues


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
    details: dict[str, Any] = {
        "method": config.method,
        "cudaAvailable": hw.cuda_available,
        "gpuCount": len(hw.gpus),
    }

    for err in config.validate():
        issues.append(PreflightIssue(severity="error", code="invalid_config", message=err))

    method = config.normalized_method
    fixture_env = os.getenv("LEVIATHAN_TRAINING_FIXTURE", "").strip() in {"1", "true", "yes", "on"}
    is_fixture = method == "fixture" or fixture_env

    if is_fixture:
        details["fixture"] = True
    else:
        _check_method_support(config, caps, issues, details)
        source = _check_base_model(config, issues, details)
        selection = _check_device(config, hw, issues, details)
        _check_dataset(config, store, issues, details)
        if source is not None and source.available:
            _check_resources(config, hw, selection, source, issues, details)

    _check_output(config, corpus_root, issues)

    if hw.disk_free_bytes is not None and hw.disk_free_bytes < 100 * _MIB:
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


def _check_method_support(
    config: TrainingConfig,
    caps: TrainingCapabilities,
    issues: list[PreflightIssue],
    details: dict[str, Any],
) -> None:
    method = config.normalized_method
    support = caps.method_status(method)
    if support is None:
        return
    details["methodSupport"] = support.public_dict()
    if support.status == MethodSupportStatus.DEPENDENCY_MISSING:
        missing = ", ".join(support.missing) or "unknown"
        code = "missing_packages"
        if method == "qlora" and support.missing == ("bitsandbytes",):
            code = "missing_bitsandbytes"
        elif method == "dpo" and "trl" in support.missing:
            code = "dpo_dependencies_missing"
        issues.append(
            PreflightIssue(
                severity="error",
                code=code,
                message=f"Required packages missing for {method}: {missing}",
            )
        )
    elif support.status == MethodSupportStatus.HARDWARE_BLOCKED:
        issues.append(
            PreflightIssue(
                severity="error",
                code="hardware_blocked",
                message=f"{method} blocked by hardware: " + "; ".join(support.reasons),
            )
        )
    elif support.status in {MethodSupportStatus.FEATURE_GATED, MethodSupportStatus.UNSUPPORTED}:
        issues.append(
            PreflightIssue(
                severity="error",
                code="method_unavailable",
                message=f"{method} is {support.status.value}",
            )
        )
    if config.flash_attention and not caps.can_use_flash_attention:
        issues.append(
            PreflightIssue(
                severity="error",
                code="flash_attention_unavailable",
                message="flash_attention requested but flash_attn is not installed or CUDA is unavailable",
            )
        )
    if config.optimizer in BNB_OPTIMIZERS and not caps.can_use_8bit_optimizer:
        issues.append(
            PreflightIssue(
                severity="error",
                code="optimizer_requires_bitsandbytes",
                message=f"optimizer {config.optimizer} requires bitsandbytes and a CUDA GPU",
            )
        )


def _check_base_model(
    config: TrainingConfig,
    issues: list[PreflightIssue],
    details: dict[str, Any],
) -> ModelSource | None:
    ref = (config.base_model_ref or "").strip()
    if not ref or ref == "unspecified":
        issues.append(
            PreflightIssue(
                severity="error",
                code="base_model_required",
                message="base_model_ref must be set for real training",
            )
        )
        return None
    source = resolve_model_source(ref, revision=config.base_model_revision)
    details["modelSource"] = source.public_dict()
    if source.kind == "gguf":
        issues.append(
            PreflightIssue(
                severity="error",
                code="gguf_not_trainable",
                message=(
                    f"base_model_ref {ref!r} is a GGUF (llama.cpp inference) model. Training requires "
                    "Hugging Face transformers weights (config.json + safetensors). Select the original "
                    "HF checkpoint instead of the GGUF quantization."
                ),
            )
        )
        return source
    if source.kind == "missing":
        issues.append(
            PreflightIssue(
                severity="error",
                code="base_model_not_local",
                message=(
                    f"base_model_ref {ref!r} is not a local model directory and is not in the local "
                    "Hugging Face cache. Trainers run offline with local_files_only=True — "
                    "download the model first."
                ),
            )
        )
        return source
    if not source.has_config:
        issues.append(
            PreflightIssue(
                severity="error",
                code="base_model_config_missing",
                message=f"config.json missing for base model at {source.path}",
            )
        )
    if not source.has_weights:
        issues.append(
            PreflightIssue(
                severity="error",
                code="base_model_weights_missing",
                message=f"no safetensors/bin weights found for base model at {source.path}",
            )
        )
    return source


def _check_device(
    config: TrainingConfig,
    hw: HardwareSnapshot,
    issues: list[PreflightIssue],
    details: dict[str, Any],
) -> DeviceSelection:
    selection = select_training_device(config, hw)
    details["selectedDevice"] = selection.public_dict()
    for err in selection.errors:
        code = "multi_gpu_unsupported" if "multi-GPU" in err else "device_not_found"
        issues.append(PreflightIssue(severity="error", code=code, message=err))
    for warn in selection.warnings:
        issues.append(PreflightIssue(severity="warning", code="device_selection", message=warn))
    method = config.normalized_method
    if not hw.cuda_available:
        if config.uses_4bit and method != "qlora":
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="no_cuda_for_4bit",
                    message="load_in_4bit requires a CUDA GPU",
                )
            )
        elif method in {"lora", "qlora", "sft", "dpo"}:
            issues.append(
                PreflightIssue(
                    severity="warning",
                    code="no_cuda",
                    message="CUDA unavailable — training would fall back to CPU (very slow)",
                )
            )
    dev = selection.device
    if dev is not None and (config.precision or "").lower() == "bf16" and dev.compute_capability:
        try:
            major = int(dev.compute_capability.split(".", 1)[0])
        except ValueError:
            major = None
        if major is not None and major < 8:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="bf16_unsupported",
                    message=f"bf16 requires compute capability >= 8.0; {dev.name} is {dev.compute_capability}",
                )
            )
    if config.flash_attention and dev is not None and dev.compute_capability:
        try:
            major = int(dev.compute_capability.split(".", 1)[0])
        except ValueError:
            major = None
        if major is not None and major < 8:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="flash_attention_unsupported_gpu",
                    message=f"flash_attention_2 requires Ampere+ (>= 8.0); {dev.name} is {dev.compute_capability}",
                )
            )
    return selection


def _check_dataset(
    config: TrainingConfig,
    store: TrainingStore | None,
    issues: list[PreflightIssue],
    details: dict[str, Any],
) -> None:
    method = config.normalized_method
    dataset_path = config.dataset_path
    if config.dataset_version_id and store is not None:
        if not store.dataset_version_exists(config.dataset_version_id):
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="dataset_missing",
                    message=f"dataset_version_id not found: {config.dataset_version_id}",
                )
            )
        elif not dataset_path:
            storage = store.dataset_version_storage_path(config.dataset_version_id)
            if storage:
                dataset_path = storage
                details["resolvedDatasetPath"] = storage
            else:
                issues.append(
                    PreflightIssue(
                        severity="error",
                        code="dataset_not_materialized",
                        message=f"dataset_version_id {config.dataset_version_id} has no storage_path",
                    )
                )
    elif not dataset_path:
        issues.append(
            PreflightIssue(
                severity="error",
                code="dataset_required",
                message="dataset_version_id or dataset_path required",
            )
        )
    if dataset_path:
        path = Path(dataset_path)
        if not path.exists():
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="dataset_path_missing",
                    message=f"dataset_path does not exist: {dataset_path}",
                )
            )
        else:
            issues.extend(check_dataset_schema(method, path))


def _check_resources(
    config: TrainingConfig,
    hw: HardwareSnapshot,
    selection: DeviceSelection,
    source: ModelSource,
    issues: list[PreflightIssue],
    details: dict[str, Any],
) -> None:
    memory = estimate_training_memory(config, model_config=source.model_config)
    details["memoryEstimate"] = memory
    if not memory.get("available"):
        return
    need = int(memory["totalBytes"])
    dev = selection.device
    if dev is not None and hw.cuda_available:
        total = dev.total_vram_bytes
        free = dev.free_vram_bytes
        if total is not None and need > total:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="vram_insufficient",
                    message=(
                        f"Estimated peak VRAM {need / _MIB:.0f} MiB exceeds total VRAM "
                        f"{total / _MIB:.0f} MiB on {dev.stable_device_id} (estimate)"
                    ),
                )
            )
        elif free is not None and need > free:
            issues.append(
                PreflightIssue(
                    severity="warning",
                    code="vram_tight",
                    message=(
                        f"Estimated peak VRAM {need / _MIB:.0f} MiB exceeds currently free VRAM "
                        f"{free / _MIB:.0f} MiB on {dev.stable_device_id} (estimate)"
                    ),
                )
            )
    host_need = int(memory.get("hostLoadBytes") or 0)
    if not hw.cuda_available or dev is None:
        host_need = max(host_need, need)
    if hw.ram_total_bytes is not None and host_need > hw.ram_total_bytes:
        issues.append(
            PreflightIssue(
                severity="error",
                code="ram_insufficient",
                message=f"Estimated host RAM {host_need / _MIB:.0f} MiB exceeds total RAM (estimate)",
            )
        )
    elif hw.ram_available_bytes is not None and host_need > hw.ram_available_bytes:
        issues.append(
            PreflightIssue(
                severity="warning",
                code="ram_tight",
                message=f"Estimated host RAM {host_need / _MIB:.0f} MiB exceeds available RAM (estimate)",
            )
        )
    if hw.disk_free_bytes is not None:
        params = int(memory.get("paramCount") or 0)
        if config.normalized_method == "sft":
            per_save = params * 2
        else:
            per_save = int(memory.get("trainableParamCount") or 0) * 4
        # HF checkpoints include optimizer state (~2x weights for adam).
        keep = int(config.save_total_limit or 3) + 1
        disk_need = per_save * 3 * keep
        details["diskEstimateBytes"] = disk_need
        if disk_need > hw.disk_free_bytes:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="disk_insufficient",
                    message=(
                        f"Estimated checkpoint/output disk {disk_need / _MIB:.0f} MiB exceeds free disk "
                        f"{hw.disk_free_bytes / _MIB:.0f} MiB (estimate)"
                    ),
                )
            )


def _check_output(config: TrainingConfig, corpus_root: Path | None, issues: list[PreflightIssue]) -> None:
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
