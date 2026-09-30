from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrainingJobStatus(str, Enum):
    """Legacy in-memory registry statuses (PreferenceBridge / TrainingRegistry)."""

    REGISTERED = "REGISTERED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DurableTrainingStatus(str, Enum):
    """Persisted training job statuses (training_jobs table)."""

    QUEUED = "queued"
    PREFLIGHT = "preflight"
    RUNNING = "running"
    EVALUATING = "evaluating"
    EXPORTING = "exporting"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


ACTIVE_DURABLE_STATUSES = frozenset(
    {
        DurableTrainingStatus.QUEUED,
        DurableTrainingStatus.PREFLIGHT,
        DurableTrainingStatus.RUNNING,
        DurableTrainingStatus.EVALUATING,
        DurableTrainingStatus.EXPORTING,
        DurableTrainingStatus.CANCELLING,
    }
)

TERMINAL_DURABLE_STATUSES = frozenset(
    {
        DurableTrainingStatus.CANCELLED,
        DurableTrainingStatus.COMPLETED,
        DurableTrainingStatus.FAILED,
        DurableTrainingStatus.INTERRUPTED,
    }
)

RESUMABLE_DURABLE_STATUSES = frozenset(
    {
        DurableTrainingStatus.INTERRUPTED,
        DurableTrainingStatus.QUEUED,
    }
)


class TrainingMethod(str, Enum):
    FIXTURE = "fixture"
    SFT = "sft"
    LORA = "lora"
    QLORA = "qlora"
    DPO = "dpo"


class PreflightVerdict(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class TrainingJob:
    """Training job registry stub — no fake training progress."""

    job_id: str
    name: str
    status: TrainingJobStatus
    objective: str
    created_at: str
    updated_at: str
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status.value,
            "objective": self.objective,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metrics": self.metrics,
            "error": self.error,
            "truth": {
                "registered_is_not_trained": True,
                "no_fabricated_metrics": True,
            },
        }


@dataclass(frozen=True)
class PackageAvailability:
    name: str
    available: bool
    version: str | None = None
    import_error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "version": self.version,
            "importError": self.import_error,
        }


class MethodSupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    HARDWARE_BLOCKED = "HARDWARE_BLOCKED"
    FEATURE_GATED = "FEATURE_GATED"


PRODUCTION_TRAINING_METHODS = ("sft", "lora", "qlora", "dpo")


@dataclass(frozen=True)
class MethodSupport:
    method: str
    status: MethodSupportStatus
    requires: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    optional_missing: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def operational(self) -> bool:
        return self.status == MethodSupportStatus.SUPPORTED

    def public_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "status": self.status.value,
            "operational": self.operational,
            "requires": list(self.requires),
            "missingPackages": list(self.missing),
            "optionalMissingPackages": list(self.optional_missing),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TrainingCapabilities:
    packages: tuple[PackageAvailability, ...]
    can_run_fixture: bool
    can_run_lora: bool
    can_run_qlora: bool
    # Durable HF/TRL DPO job (method=dpo). Pure-Python micro objective is separate.
    can_run_dpo: bool
    ready: bool
    missing_for_lora: tuple[str, ...]
    notes: tuple[str, ...] = ()
    # W11 honest method availability — never imply operational RL/GRPO without a trainer.
    can_run_reward_model: bool = False
    can_run_grpo: bool = False
    can_run_rl: bool = False
    reward_model_status: str = "FEATURE_GATED"
    grpo_status: str = "FEATURE_GATED"
    rl_status: str = "FEATURE_GATED"
    dpo_hf_status: str = "FEATURE_GATED"
    can_run_sft: bool = False
    can_run_dpo_micro: bool = True
    can_use_flash_attention: bool = False
    can_use_8bit_optimizer: bool = False
    cuda_available: bool | None = None
    method_support: dict[str, MethodSupport] = field(default_factory=dict)
    missing_for_sft: tuple[str, ...] = ()
    missing_for_qlora: tuple[str, ...] = ()
    missing_for_dpo: tuple[str, ...] = ()
    device_strategies: tuple[str, ...] = ("auto", "single")
    multi_gpu_status: str = MethodSupportStatus.UNSUPPORTED.value

    @property
    def production_methods(self) -> tuple[str, ...]:
        return tuple(
            m for m in PRODUCTION_TRAINING_METHODS
            if m in self.method_support and self.method_support[m].operational
        )

    def method_status(self, method: str) -> MethodSupport | None:
        return self.method_support.get((method or "").strip().lower())

    def public_dict(self) -> dict[str, Any]:
        return {
            "packages": [p.public_dict() for p in self.packages],
            "canRunFixture": self.can_run_fixture,
            "canRunSft": self.can_run_sft,
            "canRunLora": self.can_run_lora,
            "canRunQlora": self.can_run_qlora,
            "canRunDpo": self.can_run_dpo,
            "canRunDpoMicro": self.can_run_dpo_micro,
            "canUseFlashAttention": self.can_use_flash_attention,
            "canUse8bitOptimizer": self.can_use_8bit_optimizer,
            "cudaAvailable": self.cuda_available,
            "canRunRewardModel": self.can_run_reward_model,
            "canRunGrpo": self.can_run_grpo,
            "canRunRl": self.can_run_rl,
            "rewardModelStatus": self.reward_model_status,
            "grpoStatus": self.grpo_status,
            "rlStatus": self.rl_status,
            "dpoHfStatus": self.dpo_hf_status,
            "methodSupport": {k: v.public_dict() for k, v in self.method_support.items()},
            "productionMethods": list(self.production_methods),
            "deviceStrategies": list(self.device_strategies),
            "multiGpuStatus": self.multi_gpu_status,
            "ready": self.ready,
            "missingForSft": list(self.missing_for_sft),
            "missingForLora": list(self.missing_for_lora),
            "missingForQlora": list(self.missing_for_qlora),
            "missingForDpo": list(self.missing_for_dpo),
            "notes": list(self.notes),
            "truth": {
                "optional_ml_deps_do_not_crash_imports": True,
                "recipe_registered_is_not_operational_trainer": True,
                "fixture_is_not_production_ready": True,
                "ready_requires_production_method": True,
                "dpo_micro_is_not_durable_dpo": True,
            },
        }


@dataclass(frozen=True)
class GpuDeviceInfo:
    index: int
    name: str
    total_vram_bytes: int | None = None
    free_vram_bytes: int | None = None
    used_vram_bytes: int | None = None
    compute_capability: str | None = None
    stable_device_id: str = ""
    uuid: str | None = None
    pci_bus_id: str | None = None
    # Only populated when measured (nvidia-smi); never estimated.
    utilization_pct: float | None = None
    temperature_c: float | None = None
    # "nvidia-smi" ordinals follow PCI bus order; "torch" ordinals follow the
    # probing process' CUDA enumeration (may already be remapped by CUDA_VISIBLE_DEVICES).
    probe_source: str = "nvidia-smi"

    def public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "stableDeviceId": self.stable_device_id,
            "uuid": self.uuid,
            "pciBusId": self.pci_bus_id,
            "totalVramBytes": self.total_vram_bytes,
            "freeVramBytes": self.free_vram_bytes,
            "usedVramBytes": self.used_vram_bytes,
            "computeCapability": self.compute_capability,
            "utilizationPct": self.utilization_pct,
            "temperatureC": self.temperature_c,
            "probeSource": self.probe_source,
        }


@dataclass(frozen=True)
class HardwareSnapshot:
    cpu_model: str | None
    logical_cores: int | None
    physical_cores: int | None
    ram_total_bytes: int | None
    ram_available_bytes: int | None
    disk_free_bytes: int | None
    gpus: tuple[GpuDeviceInfo, ...]
    cuda_available: bool
    cuda_runtime_version: str | None
    torch_cuda_version: str | None
    driver_version: str | None
    supports_fp16: bool | None
    supports_bf16: bool | None
    supports_4bit: bool | None
    notes: tuple[str, ...] = ()
    measured_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "cpuModel": self.cpu_model,
            "logicalCores": self.logical_cores,
            "physicalCores": self.physical_cores,
            "ramTotalBytes": self.ram_total_bytes,
            "ramAvailableBytes": self.ram_available_bytes,
            "diskFreeBytes": self.disk_free_bytes,
            "gpus": [g.public_dict() for g in self.gpus],
            "cudaAvailable": self.cuda_available,
            "cudaRuntimeVersion": self.cuda_runtime_version,
            "torchCudaVersion": self.torch_cuda_version,
            "driverVersion": self.driver_version,
            "supportsFp16": self.supports_fp16,
            "supportsBf16": self.supports_bf16,
            "supports4bit": self.supports_4bit,
            "notes": list(self.notes),
            "measuredAt": self.measured_at,
            "truth": {
                "no_fabricated_gpu_telemetry": True,
                "gpu_absent_when_unmeasured": len(self.gpus) == 0,
            },
        }


@dataclass(frozen=True)
class PreflightIssue:
    severity: str
    code: str
    message: str

    def public_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class PreflightResult:
    verdict: PreflightVerdict
    issues: tuple[PreflightIssue, ...]
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "issues": [i.public_dict() for i in self.issues],
            "details": self.details,
        }


@dataclass(frozen=True)
class TrainingPlan:
    strategy: str
    reason: str
    effective_batch_size: int
    train_batch_size: int
    gradient_accumulation: int
    max_seq_length: int
    precision: str
    gradient_checkpointing: bool
    load_in_4bit: bool
    warnings: tuple[str, ...] = ()
    estimated: bool = True
    details: dict[str, Any] = field(default_factory=dict)
    # Planner knobs the operator asked for / planner recommends / will actually run.
    requested_config: dict[str, Any] = field(default_factory=dict)
    suggested_config: dict[str, Any] = field(default_factory=dict)
    effective_config: dict[str, Any] = field(default_factory=dict)
    suggested_changes: dict[str, Any] = field(default_factory=dict)
    suggestions_applied: bool = False
    selected_device: dict[str, Any] | None = None
    memory_estimate: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "reason": self.reason,
            "effectiveBatchSize": self.effective_batch_size,
            "trainBatchSize": self.train_batch_size,
            "gradientAccumulation": self.gradient_accumulation,
            "maxSeqLength": self.max_seq_length,
            "precision": self.precision,
            "gradientCheckpointing": self.gradient_checkpointing,
            "loadIn4bit": self.load_in_4bit,
            "warnings": list(self.warnings),
            "estimated": self.estimated,
            "details": self.details,
            "requestedConfig": dict(self.requested_config),
            "suggestedConfig": dict(self.suggested_config),
            "effectiveConfig": dict(self.effective_config),
            "suggestedChanges": dict(self.suggested_changes),
            "suggestionsApplied": self.suggestions_applied,
            "selectedDevice": dict(self.selected_device) if self.selected_device else None,
            "memoryEstimate": dict(self.memory_estimate),
            "truth": {
                "top_level_values_are_effective": True,
                "planner_never_silently_mutates_config": True,
                "multi_gpu_not_implemented": True,
            },
        }


@dataclass(frozen=True)
class DurableTrainingJob:
    job_id: str
    name: str
    status: DurableTrainingStatus
    method: str
    base_model_ref: str
    dataset_version_id: str | None
    output_dir: str | None
    config: dict[str, Any]
    planner: dict[str, Any]
    preflight: dict[str, Any]
    progress: float | None
    cancel_requested: bool
    worker_pid: int | None
    checkpoint: dict[str, Any]
    metrics_summary: dict[str, Any]
    evaluation: dict[str, Any]
    artifact_id: str | None
    error: str | None
    log_path: str | None
    trace_id: str | None
    seed: int | None
    config_hash: str | None
    environment: dict[str, Any]
    phase: str | None
    created_at: str
    started_at: str | None
    updated_at: str
    finished_at: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "name": self.name,
            "status": self.status.value,
            "phase": self.phase,
            "method": self.method,
            "baseModelRef": self.base_model_ref,
            "datasetVersionId": self.dataset_version_id,
            "outputDir": self.output_dir,
            "config": self.config,
            "planner": self.planner,
            "preflight": self.preflight,
            "progress": self.progress,
            "cancelRequested": self.cancel_requested,
            "workerPid": self.worker_pid,
            "checkpoint": self.checkpoint,
            "metricsSummary": self.metrics_summary,
            "evaluation": self.evaluation,
            "artifactId": self.artifact_id,
            "error": self.error,
            "logPath": self.log_path,
            "traceId": self.trace_id,
            "seed": self.seed,
            "configHash": self.config_hash,
            "environment": self.environment,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "finishedAt": self.finished_at,
            "truth": {"no_fabricated_metrics": True},
        }


@dataclass(frozen=True)
class MetricRecord:
    id: int | None
    job_id: str
    step: int | None
    epoch: float | None
    metric_name: str
    metric_value: float
    recorded_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "jobId": self.job_id,
            "step": self.step,
            "epoch": self.epoch,
            "metricName": self.metric_name,
            "metricValue": self.metric_value,
            "recordedAt": self.recorded_at,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    job_id: str
    step: int | None
    epoch: float | None
    path: str
    content_hash: str | None
    metrics: dict[str, Any]
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "checkpointId": self.checkpoint_id,
            "jobId": self.job_id,
            "step": self.step,
            "epoch": self.epoch,
            "path": self.path,
            "contentHash": self.content_hash,
            "metrics": self.metrics,
            "createdAt": self.created_at,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    job_id: str
    artifact_type: str
    path: str
    base_model_ref: str | None
    dataset_version_id: str | None
    method: str | None
    config_hash: str | None
    content_hash: str | None
    model_card_path: str | None
    evaluation: dict[str, Any]
    compatibility: dict[str, Any]
    registered_model_id: str | None
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "jobId": self.job_id,
            "artifactType": self.artifact_type,
            "path": self.path,
            "baseModelRef": self.base_model_ref,
            "datasetVersionId": self.dataset_version_id,
            "method": self.method,
            "configHash": self.config_hash,
            "contentHash": self.content_hash,
            "modelCardPath": self.model_card_path,
            "evaluation": self.evaluation,
            "compatibility": self.compatibility,
            "registeredModelId": self.registered_model_id,
            "createdAt": self.created_at,
            "metadata": self.metadata,
        }
