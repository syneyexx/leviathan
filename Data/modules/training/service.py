"""Durable TrainingService — create, launch, cancel, resume, inspect jobs."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from Data.backend.config import Settings
from Data.modules.common.atomic import ensure_dir
from Data.modules.common.corpus import CorpusLayout, build_corpus_layout
from Data.modules.common.process import pid_fingerprint, pid_is_alive
from Data.modules.common.secrets import redact_secrets

from .artifacts import export_artifact
from .capabilities import probe_training_capabilities
from .config import TrainingConfig
from .evaluation import evaluate_job
from .events import TrainingEventLog
from .execution_gate import (
    TrainingExecutionGateError,
    allow_trainer_ownership,
    production_requires_external,
    refuse_inline_heavy_scan,
    refuse_inline_trainer,
)
from .hardware import probe_hardware
from .launcher import TrainingLauncher
from .planner import plan_training
from .preflight import run_preflight
from .recovery import reconcile_active_jobs
from .store import TrainingStore, utc_now
from .supervisor import resolve_resume_checkpoint_path, supervise_trainer
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


def _tail_text_file(path: Path, *, max_bytes: int = 64_000) -> str:
    """Read only the trailing ``max_bytes`` of a potentially huge log file."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(max(0, size - max_bytes))
        data = handle.read(max_bytes)
    return data.decode("utf-8", errors="replace")


class TrainingService:
    """Facade over durable training store + subprocess workers."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: TrainingStore | None = None,
        corpus: CorpusLayout | None = None,
        launcher: TrainingLauncher | None = None,
        job_runtime: Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or TrainingStore(settings.database_path)
        self.corpus = corpus or build_corpus_layout(settings)
        self.launcher = launcher or TrainingLauncher()
        self.job_runtime = job_runtime
        self._processes: dict[str, Any] = {}

    def _externalize(self) -> bool:
        import os

        return (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        } and self.job_runtime is not None

    def reconcile(self) -> list[dict]:
        """Bounded PID reconcile on Control Plane. Heavy integrity sync is external."""
        results = reconcile_active_jobs(self.store, processes=self._processes)
        # Do NOT run recursive artifact hashing / registry integrity on the API path.
        # Enqueue training.integrity.verify when externalization requires it.
        if self._externalize() and production_requires_external(self.settings):
            pending = [
                job
                for job in self.store.list_jobs(limit=100)
                if job.artifact_id
                and job.status == DurableTrainingStatus.COMPLETED
            ]
            for job in pending:
                artifact = self.store.get_artifact(job.artifact_id) if job.artifact_id else None
                if artifact is None or artifact.registered_model_id:
                    continue
                try:
                    self.enqueue_integrity_verify(job.job_id)
                    results.append(
                        {
                            "jobId": job.job_id,
                            "integrityVerify": "enqueued",
                            "artifactId": job.artifact_id,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        {
                            "jobId": job.job_id,
                            "integrityVerify": "enqueue_failed",
                            "error": str(exc)[:300],
                        }
                    )
            return results
        # Test / legacy path: allow inline sync only when gate permits.
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

        if self._externalize() or production_requires_external(self.settings):
            if self.job_runtime is None:
                raise TrainingError(
                    "training_control worker required; job_runtime not bound",
                    http_status=503,
                    details={"code": "TRAINING_WORKER_UNAVAILABLE"},
                )
            # API does not hold trainer Popen — training_control worker owns the process.
            self.job_runtime.enqueue(
                capability_id="training.control",
                arguments={"training_job_id": job_id, "action": "start"},
                requested_by="training_service",
                idempotency_key=f"training:control:start:{job_id}",
                domain="training",
                domain_entity_type="training_job",
                domain_entity_id=job_id,
                worker_pool="training_control",
                resource_class="GPU_EXCLUSIVE",
                latency_class="batch",
            )
            return self.store.update_job(
                job_id,
                status=DurableTrainingStatus.QUEUED,
                phase="awaiting_worker",
                log_path=str(log_path),
                preflight=preflight.public_dict(),
            )

        # Test-only / explicit inline path.
        if not allow_trainer_ownership(settings=self.settings):
            refuse_inline_trainer(reason="production_api_spawn_blocked")
        return self._spawn_owned(
            job_id,
            config=config,
            output_dir=output_dir,
            log_path=log_path,
            events_path=events_path,
            preflight=preflight.public_dict(),
            supervise=False,
        )

    def _next_launch_generation(self, job: DurableTrainingJob) -> int:
        meta = dict(job.environment or {})
        return int(meta.get("launch_generation") or 0) + 1

    def _spawn_owned(
        self,
        job_id: str,
        *,
        config: TrainingConfig,
        output_dir: Path,
        log_path: Path,
        events_path: Path,
        preflight: dict[str, Any],
        supervise: bool = False,
        cancel_check: Any | None = None,
    ) -> DurableTrainingJob | dict[str, Any]:
        """Spawn trainer subprocess. When ``supervise=True``, wait for full lifetime."""
        if not allow_trainer_ownership(settings=self.settings):
            refuse_inline_trainer(reason="spawn_ownership_denied")

        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)

        # Idempotency: do not spawn a second trainer for a live launch generation.
        env_meta = dict(job.environment or {})
        existing_pid = job.worker_pid
        existing_fp = str(env_meta.get("pid_fingerprint") or "")
        if existing_pid and pid_is_alive(int(existing_pid)):
            live_fp = pid_fingerprint(int(existing_pid))
            if existing_fp and live_fp and existing_fp == live_fp:
                if not supervise:
                    return job
                # Adopt existing process — wait for it without spawning a duplicate.
                launch_generation = int(env_meta.get("launch_generation") or 0)
                # Wrap PID in a minimal pollable object for supervise_trainer.
                class _AdoptedProc:
                    def __init__(self, pid: int) -> None:
                        self.pid = pid
                        self.returncode: int | None = None

                    def poll(self) -> int | None:
                        if self.returncode is not None:
                            return self.returncode
                        if not pid_is_alive(self.pid):
                            self.returncode = 0
                            return 0
                        return None

                adopted = _AdoptedProc(int(existing_pid))
                supervision = supervise_trainer(
                    store=self.store,
                    job_id=job_id,
                    proc=adopted,  # type: ignore[arg-type]
                    launch_generation=launch_generation,
                    pid_fp=existing_fp,
                    cancel_check=cancel_check,
                )
                final = self.store.get_job(job_id) or job
                return {
                    "training_job": final,
                    "supervision": supervision,
                    "adopted": True,
                }

        launch_generation = self._next_launch_generation(job)
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
        if proc.returncode is not None and proc.returncode != 0:
            raise TrainingError(
                f"TRAINER_START_FAILED: exit_code={proc.returncode}",
                http_status=500,
                details={"code": "TRAINER_START_FAILED", "exit_code": proc.returncode},
            )
        fp = pid_fingerprint(proc.pid) if proc.pid else ""
        env_meta.update(
            {
                "launch_generation": launch_generation,
                "pid_fingerprint": fp,
                "trainer_pid": proc.pid,
                "control_owner": "training_control" if supervise else "inline_test",
            }
        )
        updated = self.store.update_job(
            job_id,
            status=DurableTrainingStatus.RUNNING,
            phase="running",
            worker_pid=proc.pid,
            started_at=utc_now(),
            log_path=str(log_path),
            preflight=preflight,
            environment=env_meta,
        )
        if not supervise:
            return updated

        supervision = supervise_trainer(
            store=self.store,
            job_id=job_id,
            proc=proc,
            launch_generation=launch_generation,
            pid_fp=fp,
            cancel_check=cancel_check,
        )
        final = self.store.get_job(job_id) or updated
        self._processes.pop(job_id, None)
        return {
            "training_job": final,
            "supervision": supervision,
            "adopted": False,
        }

    def execute_control_start(
        self,
        job_id: str,
        *,
        cancel_check: Any | None = None,
    ) -> dict[str, Any]:
        """Worker-side start: spawn AND supervise trainer for full lifetime.

        GPU_EXCLUSIVE reservation is held by the training_control handler until
        this method returns (trainer terminal).
        """
        if not allow_trainer_ownership(settings=self.settings):
            refuse_inline_trainer(reason="control_start_outside_training_control")
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        config = TrainingConfig.from_dict(job.config)
        output_dir = Path(job.output_dir or (self.corpus.training_adapters / job_id))
        ensure_dir(output_dir)
        log_path = Path(job.log_path or (self.corpus.training_logs / job_id / "worker.log"))
        events_path = self.corpus.training_logs / job_id / "events.jsonl"
        ensure_dir(log_path.parent)
        result = self._spawn_owned(
            job_id,
            config=config,
            output_dir=output_dir,
            log_path=log_path,
            events_path=events_path,
            preflight=dict(job.preflight or {}),
            supervise=True,
            cancel_check=cancel_check,
        )
        if isinstance(result, DurableTrainingJob):
            return {"training_job": result, "supervision": {}, "adopted": False}
        return result

    def enqueue_integrity_verify(self, job_id: str) -> dict[str, Any]:
        if self.job_runtime is None:
            if production_requires_external(self.settings):
                refuse_inline_heavy_scan(reason="no_job_runtime")
            from Data.modules.models.store import ModelStore
            from .model_registration import sync_completed_artifacts_to_models

            synced = sync_completed_artifacts_to_models(
                model_store=ModelStore(self.settings.database_path),
                training_store=self.store,
            )
            return {"syncedModels": synced, "executed_via": "inline_test"}
        job = self.job_runtime.enqueue(
            capability_id="training.integrity.verify",
            arguments={"training_job_id": job_id},
            requested_by="training_service",
            idempotency_key=f"training:integrity:verify:{job_id}",
            domain="training",
            domain_entity_type="training_job",
            domain_entity_id=job_id,
            worker_pool="training_control",
            resource_class="IO_HEAVY",
            latency_class="batch",
        )
        return {"job_id": job.job_id, "capability_id": "training.integrity.verify"}

    def enqueue_checkpoint_verify(self, job_id: str, *, checkpoint_path: str | None = None) -> dict[str, Any]:
        if self.job_runtime is None:
            if production_requires_external(self.settings):
                refuse_inline_heavy_scan(reason="no_job_runtime")
            return self.execute_checkpoint_verify(job_id, checkpoint_path=checkpoint_path)
        job = self.job_runtime.enqueue(
            capability_id="training.checkpoint.verify",
            arguments={"training_job_id": job_id, "checkpoint_path": checkpoint_path},
            requested_by="training_service",
            idempotency_key=f"training:checkpoint:verify:{job_id}:{checkpoint_path or 'latest'}",
            domain="training",
            domain_entity_type="training_job",
            domain_entity_id=job_id,
            worker_pool="training_control",
            resource_class="IO_HEAVY",
            latency_class="batch",
        )
        return {"job_id": job.job_id, "capability_id": "training.checkpoint.verify"}

    def enqueue_dataset_hash(self, job_id: str, *, path: str) -> dict[str, Any]:
        if self.job_runtime is None:
            if production_requires_external(self.settings):
                refuse_inline_heavy_scan(reason="no_job_runtime")
            return self.execute_dataset_hash(job_id, path=path)
        job = self.job_runtime.enqueue(
            capability_id="training.dataset.hash",
            arguments={"training_job_id": job_id, "path": path},
            requested_by="training_service",
            idempotency_key=f"training:dataset:hash:{job_id}:{path}",
            domain="training",
            domain_entity_type="training_job",
            domain_entity_id=job_id,
            worker_pool="training_control",
            resource_class="IO_HEAVY",
            latency_class="batch",
        )
        return {"job_id": job.job_id, "capability_id": "training.dataset.hash"}

    def execute_integrity_verify(self, job_id: str) -> dict[str, Any]:
        from Data.modules.models.store import ModelStore
        from .model_registration import sync_completed_artifacts_to_models

        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        synced = sync_completed_artifacts_to_models(
            model_store=ModelStore(self.settings.database_path),
            training_store=self.store,
            job_id=job_id,
        )
        return {"job_id": job_id, "syncedModels": synced, "executed_via": "training_control"}

    def execute_checkpoint_verify(
        self, job_id: str, *, checkpoint_path: str | None = None
    ) -> dict[str, Any]:
        from .checkpoint_verify import verify_checkpoint

        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        path = checkpoint_path or (job.checkpoint or {}).get("path")
        if not path:
            raise TrainingError(
                "No checkpoint path to verify",
                http_status=404,
                details={"code": "TRAINING_CHECKPOINT_INVALID"},
            )
        report = verify_checkpoint(Path(str(path)), job=job)
        return report

    def execute_dataset_hash(self, job_id: str, *, path: str) -> dict[str, Any]:
        from .dataset_hash import hash_training_dataset

        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        report = hash_training_dataset(Path(path))
        if report.get("changed"):
            raise TrainingError(
                "TRAINING_DATASET_CHANGED: content mutated during hash",
                http_status=409,
                details={"code": "TRAINING_DATASET_CHANGED", **report},
            )
        cfg = dict(job.config or {})
        cfg["dataset_content_hash"] = report.get("content_hash")
        cfg["dataset_hash_manifest"] = {
            "file_count": report.get("file_count"),
            "total_bytes": report.get("total_bytes"),
            "content_hash": report.get("content_hash"),
        }
        self.store.update_job(job_id, config=cfg)
        return report

    def get_job(self, job_id: str) -> DurableTrainingJob | None:
        return self.store.get_job(job_id)

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[DurableTrainingJob]:
        return self.store.list_jobs(status=status, limit=limit)

    def cancel_job(self, job_id: str, *, wait_seconds: float = 0.0) -> DurableTrainingJob:
        """Request cancellation and return promptly.

        ``wait_seconds`` retained for compatibility but defaults to 0 — API must not
        block waiting for a trainer process to die. Supervisor/worker finalize CANCELLING.
        """
        job = self.store.get_job(job_id)
        if job is None:
            raise TrainingError("Training job not found", http_status=404)
        if job.status in TERMINAL_DURABLE_STATUSES:
            raise TrainingError(f"Job already terminal: {job.status.value}", http_status=409)

        job = self.store.request_cancel(job_id)
        events_path = self.corpus.training_logs / job_id / "events.jsonl"
        TrainingEventLog(events_path).emit("cancel_requested")

        # Optional brief reconcile for tests; production API uses wait_seconds=0.
        deadline = time.time() + max(0.0, float(wait_seconds or 0.0))
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
        # Prefer last checkpoint path when present — exact directory semantics.
        cfg = dict(job.config)
        raw_ckpt = (job.checkpoint or {}).get("path")
        if raw_ckpt:
            resolved = resolve_resume_checkpoint_path(raw_ckpt)
            if resolved:
                cfg["resume_from_checkpoint"] = resolved
                cfg["resume_from_step"] = (job.checkpoint or {}).get("step")
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
            text = _tail_text_file(Path(path), max_bytes=max(1024, int(max_bytes)))
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
