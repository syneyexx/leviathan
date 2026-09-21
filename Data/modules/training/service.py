"""Durable TrainingService — create, launch, cancel, resume, inspect jobs."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from Data.backend.config import Settings
from Data.modules.common.atomic import ensure_dir
from Data.modules.common.corpus import CorpusLayout, build_corpus_layout
from Data.modules.common.secrets import redact_secrets

from .artifacts import export_artifact
from .capabilities import probe_training_capabilities
from .config import TrainingConfig
from .evaluation import evaluate_job
from .events import TrainingEventLog
from .hardware import probe_hardware
from .launcher import TrainingLauncher
from .planner import plan_training
from .preflight import run_preflight
from .recovery import reconcile_active_jobs
from .store import TrainingStore, utc_now
from .types import (
    DurableTrainingJob,
    DurableTrainingStatus,
    PreflightVerdict,
    RESUMABLE_DURABLE_STATUSES,
    TERMINAL_DURABLE_STATUSES,
)


class TrainingError(Exception):
    def __init__(self, message: str, *, http_status: int = 400, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def public_dict(self) -> dict[str, Any]:
        return {"error": self.message, "details": self.details}


class TrainingService:
    """Facade over durable training store + subprocess workers."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: TrainingStore | None = None,
        corpus: CorpusLayout | None = None,
        launcher: TrainingLauncher | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or TrainingStore(settings.database_path)
        self.corpus = corpus or build_corpus_layout(settings)
        self.launcher = launcher or TrainingLauncher()
        self._processes: dict[str, Any] = {}

    def reconcile(self) -> list[dict]:
        results = reconcile_active_jobs(self.store, processes=self._processes)
        try:
            from Data.modules.models.store import ModelStore
            from .model_registration import sync_completed_artifacts_to_models

            synced = sync_completed_artifacts_to_models(
                model_store=ModelStore(self.settings.database_path),
                training_store=self.store,
            )
            if synced:
                results.append({"syncedModels": synced})
        except Exception as exc:  # noqa: BLE001 — registry sync must not break reconcile
            results.append({"modelRegistrySyncError": str(exc)})
        return results

    def capabilities(self) -> dict[str, Any]:
        return probe_training_capabilities().public_dict()

    def hardware(self) -> dict[str, Any]:
        return probe_hardware(corpus_path=self.corpus.training).public_dict()

    def preflight(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = TrainingConfig.from_dict(payload)
        hw = probe_hardware(corpus_path=self.corpus.training)
        caps = probe_training_capabilities()
        result = run_preflight(
            config,
            store=self.store,
            hardware=hw,
            capabilities=caps,
            corpus_root=self.corpus.training,
        )
        return result.public_dict()

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = TrainingConfig.from_dict(payload)
        hw = probe_hardware(corpus_path=self.corpus.training)
        caps = probe_training_capabilities()
        return plan_training(config, hw, caps).public_dict()

    def create_job(self, payload: dict[str, Any], *, auto_start: bool = False) -> DurableTrainingJob:
        config = TrainingConfig.from_dict(payload)
        errors = config.validate()
        if errors:
            raise TrainingError("Invalid training config", details={"errors": errors})

        hw = probe_hardware(corpus_path=self.corpus.training)
        caps = probe_training_capabilities()
        plan = plan_training(config, hw, caps)
        preflight = run_preflight(
            config,
            store=self.store,
            hardware=hw,
            capabilities=caps,
            corpus_root=self.corpus.training,
        )

        job_id = str(uuid.uuid4())
        job_dir = self.corpus.training_jobs / job_id
        ensure_dir(job_dir)
        output_dir = Path(config.output_dir) if config.output_dir else (self.corpus.training_adapters / job_id)
        ensure_dir(output_dir)
        log_path = self.corpus.training_logs / job_id / "worker.log"
        ensure_dir(log_path.parent)

        # Apply planner suggestions into stored config snapshot (non-destructive copy).
        cfg = config.to_dict()
        cfg["train_batch_size"] = plan.train_batch_size
        cfg["gradient_accumulation"] = plan.gradient_accumulation
        cfg["max_seq_length"] = plan.max_seq_length
        cfg["precision"] = plan.precision
        cfg["gradient_checkpointing"] = plan.gradient_checkpointing
        cfg["load_in_4bit"] = plan.load_in_4bit
        cfg["output_dir"] = str(output_dir)
        stored = TrainingConfig.from_dict(cfg)

        job = self.store.create_job(
            job_id=job_id,
            name=stored.name,
            method=stored.method,
            base_model_ref=stored.base_model_ref,
            dataset_version_id=stored.dataset_version_id,
            output_dir=str(output_dir),
            config=stored.public_dict(),
            planner=plan.public_dict(),
            preflight=preflight.public_dict(),
            environment={
                "capabilities": caps.public_dict(),
                "hardware": {
                    "cudaAvailable": hw.cuda_available,
                    "gpuCount": len(hw.gpus),
                    "ramAvailableBytes": hw.ram_available_bytes,
                },
            },
            seed=stored.seed,
            config_hash=stored.config_hash(),
            log_path=str(log_path),
            trace_id=str(uuid.uuid4()),
        )
        if auto_start:
            return self.start_job(job.job_id)
        return job

    def start_job(self, job_id: str) -> DurableTrainingJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        if job.status in TERMINAL_DURABLE_STATUSES and job.status != DurableTrainingStatus.INTERRUPTED:
            if job.status != DurableTrainingStatus.QUEUED:
                raise TrainingError(
                    f"Cannot start job in status {job.status.value}",
                    http_status=409,
                )
        if job.status not in {
            DurableTrainingStatus.QUEUED,
            DurableTrainingStatus.INTERRUPTED,
        }:
            raise TrainingError(
                f"Cannot start job in status {job.status.value}",
                http_status=409,
            )

        config = TrainingConfig.from_dict(job.config)
        hw = probe_hardware(corpus_path=self.corpus.training)
        caps = probe_training_capabilities()
        preflight = run_preflight(
            config,
            store=self.store,
            hardware=hw,
            capabilities=caps,
            corpus_root=self.corpus.training,
        )
        self.store.update_job(
            job_id,
            status=DurableTrainingStatus.PREFLIGHT,
            phase="preflight",
            preflight=preflight.public_dict(),
        )
        if preflight.verdict == PreflightVerdict.BLOCKED:
            return self.store.update_job(
                job_id,
                status=DurableTrainingStatus.FAILED,
                phase="failed",
                finished_at=utc_now(),
                error="Preflight blocked: "
                + "; ".join(i.message for i in preflight.issues if i.severity == "error"),
                preflight=preflight.public_dict(),
            )

        output_dir = Path(job.output_dir or (self.corpus.training_adapters / job_id))
        ensure_dir(output_dir)
        log_path = Path(job.log_path or (self.corpus.training_logs / job_id / "worker.log"))
        events_path = self.corpus.training_logs / job_id / "events.jsonl"
        ensure_dir(log_path.parent)

        # Clear prior cancel flag on resume/start
        self.store.update_job(job_id, cancel_requested=False, error=None, finished_at=None)

        proc = self.launcher.spawn(
            job_id=job_id,
            db_path=self.store.db_path,
            config=config,
            output_dir=output_dir,
            log_path=log_path,
            events_path=events_path,
            cwd=Path(__file__).resolve().parents[3],  # repo root (/workspace)
        )
        self._processes[job_id] = proc
        # Reap immediately if spawn failed instantly.
        proc.poll()
        return self.store.update_job(
            job_id,
            status=DurableTrainingStatus.RUNNING,
            phase="running",
            worker_pid=proc.pid,
            started_at=utc_now(),
            log_path=str(log_path),
            preflight=preflight.public_dict(),
        )

    def get_job(self, job_id: str) -> DurableTrainingJob | None:
        return self.store.get_job(job_id)

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[DurableTrainingJob]:
        return self.store.list_jobs(status=status, limit=limit)

    def cancel_job(self, job_id: str, *, wait_seconds: float = 10.0) -> DurableTrainingJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        if job.status in TERMINAL_DURABLE_STATUSES:
            raise TrainingError(f"Job already terminal: {job.status.value}", http_status=409)

        job = self.store.request_cancel(job_id)
        events_path = self.corpus.training_logs / job_id / "events.jsonl"
        TrainingEventLog(events_path).emit("cancel_requested")

        deadline = time.time() + max(0.0, wait_seconds)
        while time.time() < deadline:
            current = self.store.get_job(job_id)
            if current is None:
                break
            if current.status == DurableTrainingStatus.CANCELLED:
                return current
            pid = current.worker_pid
            if pid is not None:
                from Data.modules.common.process import pid_is_alive

                if not pid_is_alive(pid):
                    return self.store.update_job(
                        job_id,
                        status=DurableTrainingStatus.CANCELLED,
                        phase="cancelled",
                        finished_at=utc_now(),
                        error="Cancelled (worker exited)",
                        worker_pid=None,
                    )
            time.sleep(0.05)
        # Leave cancelling if still running — recovery will finalize if process dies.
        return self.store.get_job(job_id) or job

    def resume_job(self, job_id: str) -> DurableTrainingJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        if job.status not in RESUMABLE_DURABLE_STATUSES:
            raise TrainingError(
                f"Job status {job.status.value} is not resumable",
                http_status=409,
            )
        # Prefer last checkpoint path when present.
        cfg = dict(job.config)
        if job.checkpoint.get("path"):
            cfg["resume_from_checkpoint"] = str(Path(job.checkpoint["path"]).parent)
        self.store.update_job(
            job_id,
            status=DurableTrainingStatus.QUEUED,
            phase="queued",
            config=cfg,
            finished_at=None,
            error=None,
            cancel_requested=False,
        )
        return self.start_job(job_id)

    def checkpoints(self, job_id: str) -> list[dict[str, Any]]:
        if self.store.get_job(job_id) is None:
            raise TrainingError("Training job not found", http_status=404)
        return [c.public_dict() for c in self.store.list_checkpoints(job_id)]

    def metrics(self, job_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        if self.store.get_job(job_id) is None:
            raise TrainingError("Training job not found", http_status=404)
        return [m.public_dict() for m in self.store.list_metrics(job_id, limit=limit)]

    def logs(self, job_id: str, *, max_bytes: int = 64_000) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        text = ""
        path = job.log_path
        if path and Path(path).exists():
            data = Path(path).read_bytes()
            if len(data) > max_bytes:
                data = data[-max_bytes:]
            text = data.decode("utf-8", errors="replace")
        events_path = self.corpus.training_logs / job_id / "events.jsonl"
        events = TrainingEventLog(events_path).read(limit=200)
        return {
            "jobId": job_id,
            "logPath": path,
            "text": redact_secrets(text),
            "events": events,
        }

    def evaluate(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        return evaluate_job(self.store, job)

    def export(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        if job.status != DurableTrainingStatus.COMPLETED:
            raise TrainingError("Export requires a completed job", http_status=409)
        return export_artifact(self.store, job, export_root=self.corpus.training_exports)

    def wait_until_terminal(self, job_id: str, *, timeout: float = 60.0) -> DurableTrainingJob:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.store.get_job(job_id)
            if job is None:
                raise TrainingError("Training job not found", http_status=404)
            if job.status in TERMINAL_DURABLE_STATUSES:
                return job
            time.sleep(0.05)
        raise TrainingError("Timed out waiting for job terminal state", http_status=504)
