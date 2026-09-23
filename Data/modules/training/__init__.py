"""Training subsystem — durable jobs, optional LoRA, honest stubs where needed."""

from .artifacts import export_artifact, list_job_artifacts
from .capabilities import probe_training_capabilities, safe_import
from .config import TrainingConfig
from .evaluation import evaluate_job
from .events import TrainingEventLog
from .hardware import probe_hardware
from .launcher import TrainingLauncher
from .integrity import IntegrityReport, verify_artifact_integrity
from .model_registration import register_training_artifact_as_model, sync_completed_artifacts_to_models
from .planner import plan_training
from .preferences import PreferenceBridge
from .preflight import run_preflight
from .recipes import (
    NEURO_RECIPES,
    FixtureRecipeTrainer,
    RecipeRun,
    RecipeRunStatus,
    TrainingRecipe,
    TrainingRecipeRegistry,
)
from .neuro_worker import EphemeralRecipeWorkerTrainer, build_neuro_recipe_trainer
from .recovery import reconcile_active_jobs
from .registry import TrainingRegistry
from .service import TrainingError, TrainingService
from .store import TrainingStore
from .types import (
    ACTIVE_DURABLE_STATUSES,
    ArtifactRecord,
    CheckpointRecord,
    DurableTrainingJob,
    DurableTrainingStatus,
    HardwareSnapshot,
    MetricRecord,
    PreflightResult,
    PreflightVerdict,
    RESUMABLE_DURABLE_STATUSES,
    TERMINAL_DURABLE_STATUSES,
    TrainingCapabilities,
    TrainingJob,
    TrainingJobStatus,
    TrainingMethod,
    TrainingPlan,
)

__all__ = [
    "ACTIVE_DURABLE_STATUSES",
    "ArtifactRecord",
    "CheckpointRecord",
    "DurableTrainingJob",
    "DurableTrainingStatus",
    "EphemeralRecipeWorkerTrainer",
    "FixtureRecipeTrainer",
    "HardwareSnapshot",
    "IntegrityReport",
    "MetricRecord",
    "NEURO_RECIPES",
    "PreferenceBridge",
    "PreflightResult",
    "PreflightVerdict",
    "RESUMABLE_DURABLE_STATUSES",
    "RecipeRun",
    "RecipeRunStatus",
    "TERMINAL_DURABLE_STATUSES",
    "TrainingCapabilities",
    "TrainingConfig",
    "TrainingError",
    "TrainingEventLog",
    "TrainingJob",
    "TrainingJobStatus",
    "TrainingLauncher",
    "TrainingMethod",
    "TrainingPlan",
    "TrainingRecipe",
    "TrainingRecipeRegistry",
    "TrainingRegistry",
    "TrainingService",
    "TrainingStore",
    "build_neuro_recipe_trainer",
    "evaluate_job",
    "export_artifact",
    "list_job_artifacts",
    "plan_training",
    "probe_hardware",
    "probe_training_capabilities",
    "reconcile_active_jobs",
    "register_training_artifact_as_model",
    "run_preflight",
    "safe_import",
    "sync_completed_artifacts_to_models",
    "verify_artifact_integrity",
]
