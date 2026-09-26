"""FastAPI routes for the durable TrainingService + flywheel surface leftovers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.training import TrainingError, TrainingService


def raise_training_error(exc: TrainingError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class TrainingJobCreate(BaseModel):
    name: str = Field(default="training", min_length=1, max_length=200)
    method: str = Field(default="lora", min_length=1, max_length=40)
    base_model_ref: str = Field(default="unspecified", max_length=500)
    dataset_version_id: str | None = None
    dataset_path: str | None = None
    output_dir: str | None = None
    seed: int = 42
    epochs: float | None = 1.0
    max_steps: int | None = None
    train_batch_size: int = 1
    eval_batch_size: int = 1
    gradient_accumulation: int = 1
    learning_rate: float = 2e-4
    warmup_steps: int = 0
    weight_decay: float = 0.0
    max_seq_length: int = 512
    logging_steps: int = 1
    save_steps: int = 50
    precision: str = "fp32"
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    lora_target_modules: list[str] = Field(default_factory=lambda: ["q_proj", "v_proj"])
    gradient_checkpointing: bool = False
    load_in_4bit: bool = False
    fixture_steps: int = 5
    fixture_sleep_ms: int = 50
    mixture_id: str | None = None
    mixture_content_hash: str | None = None
    auto_start: bool = False


class PreflightRequest(BaseModel):
    name: str = "training"
    method: str = "lora"
    base_model_ref: str = "unspecified"
    dataset_version_id: str | None = None
    dataset_path: str | None = None
    output_dir: str | None = None
    seed: int = 42
    epochs: float | None = 1.0
    max_steps: int | None = None
    train_batch_size: int = 1
    gradient_accumulation: int = 1
    learning_rate: float = 2e-4
    max_seq_length: int = 512
    precision: str = "fp32"
    load_in_4bit: bool = False
    fixture_steps: int = 5
    fixture_sleep_ms: int = 50


class TrainingCreateRequest(BaseModel):
    name: str = Field(default="training", min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2000)


class PreferenceFromVerificationRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    recipe_id: str = Field(default="pref_dpo_v1", min_length=1, max_length=80)


class HumanPreferenceRequest(BaseModel):
    prompt: str = Field(default="human preference", min_length=1, max_length=8000)
    preferred_text: str = Field(min_length=1, max_length=20000)
    rejected_text: str = Field(min_length=1, max_length=20000)
    recipe_id: str = Field(default="pref_dpo_v1", min_length=1, max_length=80)
    note: str = ""
    annotator: str | None = None
    rubric: str | None = None
    profile: str | None = None


class SyntheticGenerateRequest(BaseModel):
    prompts: list[str] = Field(min_length=1)
    generator_model: str = "fixture-synth-v1"
    prompt_template: str = "answer:{prompt}"
    seed: int = 42
    teacher_ensemble: list[str] = Field(default_factory=list)


class ActiveMineRequest(BaseModel):
    events: list[dict] = Field(default_factory=list)


class ActiveGovernRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=120)
    note: str = ""


def build_training_router(service: TrainingService) -> APIRouter:
    router = APIRouter(tags=["training"])

    @router.get("/api/training/capabilities")
    def capabilities() -> dict:
        return {"capabilities": service.capabilities()}

    @router.get("/api/training/hardware")
    def hardware() -> dict:
        return {"hardware": service.hardware()}

    @router.post("/api/training/preflight")
    def preflight(payload: PreflightRequest) -> dict:
        return {"preflight": service.preflight(payload.model_dump())}

    @router.post("/api/training/plan")
    def plan(payload: PreflightRequest) -> dict:
        return {"plan": service.plan(payload.model_dump())}

    @router.get("/api/training/jobs")
    def list_jobs(status: str | None = None, limit: int = 100) -> dict:
        jobs = service.list_jobs(status=status, limit=limit)
        return {"jobs": [j.public_dict() for j in jobs]}

    @router.post("/api/training/jobs")
    def create_job(payload: TrainingJobCreate) -> dict:
        data = payload.model_dump()
        auto_start = bool(data.pop("auto_start", False))
        try:
            job = service.create_job(data, auto_start=auto_start)
        except TrainingError as exc:
            raise_training_error(exc)
        return {"job": job.public_dict()}

    @router.get("/api/training/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Training job not found")
        return {"job": job.public_dict()}

    @router.post("/api/training/jobs/{job_id}/start")
    def start_job(job_id: str) -> dict:
        try:
            job = service.start_job(job_id)
        except TrainingError as exc:
            raise_training_error(exc)
        return {"job": job.public_dict()}

    @router.post("/api/training/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        try:
            job = service.cancel_job(job_id)
        except TrainingError as exc:
            raise_training_error(exc)
        return {"job": job.public_dict()}

    @router.post("/api/training/jobs/{job_id}/resume")
    def resume_job(job_id: str) -> dict:
        try:
            job = service.resume_job(job_id)
        except TrainingError as exc:
            raise_training_error(exc)
        return {"job": job.public_dict()}

    @router.get("/api/training/jobs/{job_id}/checkpoints")
    def checkpoints(job_id: str) -> dict:
        try:
            items = service.checkpoints(job_id)
        except TrainingError as exc:
            raise_training_error(exc)
        return {"checkpoints": items}

    @router.get("/api/training/jobs/{job_id}/metrics")
    def metrics(job_id: str, limit: int = 500) -> dict:
        try:
            items = service.metrics(job_id, limit=limit)
        except TrainingError as exc:
            raise_training_error(exc)
        return {"metrics": items}

    @router.get("/api/training/jobs/{job_id}/logs")
    def logs(job_id: str) -> dict:
        try:
            return service.logs(job_id)
        except TrainingError as exc:
            raise_training_error(exc)

    @router.post("/api/training/jobs/{job_id}/evaluate")
    def evaluate(job_id: str) -> dict:
        try:
            return {"evaluation": service.evaluate(job_id)}
        except TrainingError as exc:
            raise_training_error(exc)

    @router.post("/api/training/jobs/{job_id}/export")
    def export(job_id: str) -> dict:
        try:
            return {"export": service.export(job_id)}
        except TrainingError as exc:
            raise_training_error(exc)

    @router.post("/api/training/reconcile")
    def reconcile() -> dict:
        return {"reconciled": service.reconcile()}

    return router


def build_training_surface_router(
    *,
    settings: Any,
    training_service: Any,
    training_registry: Any,
    training_recipes: Any,
    preference_bridge: Any,
    preference_store: Any,
    verification_reports: Any,
    synthetic_data_service: Any,
    active_learning_miner: Any,
) -> APIRouter:
    """Legacy preference / recipe / synthetic / active-learning surfaces under /api/training."""
    router = APIRouter(tags=["training-surface"])

    @router.get("/api/training")
    def list_training() -> dict:
        """Legacy listing: preference-bridge registry intents (registered ≠ trained).

        Durable training jobs live under ``/api/training/jobs``.
        """
        return {
            "jobs": [item.public_dict() for item in training_registry.list()],
            "durable_jobs": [item.public_dict() for item in training_service.list_jobs(limit=50)],
            "truth": {
                "registered_is_not_trained": True,
                "durable_jobs_path": "/api/training/jobs",
            },
        }

    @router.get("/api/training/recipes")
    def list_training_recipes() -> dict:
        return {"recipes": [item.public_dict() for item in training_recipes.list()]}

    @router.post("/api/training/preferences/from-verification")
    def training_preferences_from_verification(payload: PreferenceFromVerificationRequest) -> dict:
        if training_recipes.get(payload.recipe_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown recipe: {payload.recipe_id}")
        reports = verification_reports.list(limit=payload.limit)
        jobs = preference_bridge.register_from_verification_reports(
            reports,
            recipe_id=payload.recipe_id,
        )
        return {
            "registered": [item.public_dict() for item in jobs],
            "source_reports": len(reports),
            "truth": {
                "registered_is_not_trained": True,
                "preference_labels_not_fabricated": True,
            },
        }

    @router.post("/api/training/preferences")
    def create_human_preference(payload: HumanPreferenceRequest) -> dict:
        if not settings.features.posttraining_flywheel:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_POSTTRAINING_FLYWHEEL=false"})
        try:
            job = preference_bridge.register_human_preference(
                preferred_text=payload.preferred_text,
                rejected_text=payload.rejected_text,
                prompt=payload.prompt,
                recipe_id=payload.recipe_id,
                note=payload.note,
                annotator=payload.annotator,
                rubric=payload.rubric,
                profile=payload.profile,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record = preference_bridge.last_preference_record
        return {
            "job": job.public_dict(),
            "preference": record.public_dict() if record else None,
            "truth": {"preference_labels_not_fabricated": True, "registered_is_not_trained": True},
        }

    @router.get("/api/training/preferences")
    def list_preferences(limit: int = 50, source: str | None = None) -> dict:
        return {
            "preferences": [p.public_dict() for p in preference_store.list(limit=limit, source=source)],
        }

    @router.post("/api/training/synthetic/generate")
    def generate_synthetic(payload: SyntheticGenerateRequest) -> dict:
        if not settings.features.posttraining_flywheel:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_POSTTRAINING_FLYWHEEL=false"})
        batch = synthetic_data_service.generate(
            prompts=payload.prompts,
            generator_model=payload.generator_model,
            prompt_template=payload.prompt_template,
            seed=payload.seed,
            teacher_ensemble=payload.teacher_ensemble,
        )
        return {"batch": batch.public_dict()}

    @router.post("/api/training/active-learning/mine")
    def mine_active_learning(payload: ActiveMineRequest) -> dict:
        if not settings.features.posttraining_flywheel:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_POSTTRAINING_FLYWHEEL=false"})
        mined = active_learning_miner.mine_from_events(payload.events)
        return {"candidates": [c.public_dict() for c in mined]}

    @router.post("/api/training/active-learning/{candidate_id}/govern")
    def govern_active_learning(candidate_id: str, payload: ActiveGovernRequest) -> dict:
        try:
            cand = active_learning_miner.govern(candidate_id, operator=payload.operator, note=payload.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"candidate": cand.public_dict()}

    @router.post("/api/training")
    def create_training(payload: TrainingCreateRequest) -> dict:
        """Legacy preference/intent registration — does not start real training."""
        job = training_registry.register(name=payload.name, objective=payload.objective)
        return {
            "job": job.public_dict(),
            "truth": {
                "registered_is_not_trained": True,
                "start_real_training_at": "/api/training/jobs",
            },
        }

    return router
