"""FastAPI routes for the durable TrainingService."""

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
