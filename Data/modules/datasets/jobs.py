"""Background dataset jobs with cancel and interrupt reconcile."""

from __future__ import annotations

import os
import threading
import traceback
from typing import Any, Callable

from Data.modules.common.process import pid_is_alive
from Data.modules.common.secrets import redact_secrets

from .store import DatasetStore, utc_now
from .types import DatasetJob, DatasetJobStatus


JobHandler = Callable[[DatasetJob], dict[str, Any]]


class DatasetJobRunner:
    """In-process worker for dataset_jobs with cancel/interrupt reconciliation."""

    def __init__(
        self,
        store: DatasetStore,
        handlers: dict[str, JobHandler],
    ) -> None:
        self.store = store
        self.handlers = handlers
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def reconcile_interrupted(self) -> list[DatasetJob]:
        """Mark RUNNING jobs whose worker PID is dead as INTERRUPTED."""
        updated: list[DatasetJob] = []
        for job in self.store.list_running_jobs():
            pid = job.worker_pid
            if pid is None:
                # No PID recorded — treat as interrupted if not this process's worker
                updated.append(
                    self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.INTERRUPTED,
                        error="Worker lost without PID (process interrupt)",
                        finished_at=utc_now(),
                        worker_pid=None,
                    )
                )
                continue
            if pid == os.getpid():
                # Still us — leave running
                continue
            if not pid_is_alive(pid):
                updated.append(
                    self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.INTERRUPTED,
                        error=f"Worker PID {pid} is not alive",
                        finished_at=utc_now(),
                        worker_pid=None,
                    )
                )
        return updated

    def is_cancel_requested(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        return bool(job and job.cancel_requested)

    def process_next(self) -> DatasetJob | None:
        self.reconcile_interrupted()
        job = self.store.claim_next_queued()
        if job is None:
            return None
        # Re-check cancel between claim and run
        fresh = self.store.get_job(job.job_id)
        if fresh and fresh.cancel_requested:
            return self.store.update_job(
                job.job_id,
                status=DatasetJobStatus.CANCELLED,
                finished_at=utc_now(),
                error="cancelled",
                worker_pid=None,
            )
        self.store.update_job(job.job_id, worker_pid=os.getpid(), phase="starting", progress=0.0)
        handler = self.handlers.get(job.job_type.value)
        if handler is None:
            return self.store.update_job(
                job.job_id,
                status=DatasetJobStatus.FAILED,
                error=f"No handler for job type {job.job_type.value}",
                finished_at=utc_now(),
                worker_pid=None,
            )
        try:
            if self.is_cancel_requested(job.job_id):
                return self.store.update_job(
                    job.job_id,
                    status=DatasetJobStatus.CANCELLED,
                    finished_at=utc_now(),
                    error="cancelled",
                    worker_pid=None,
                )
            result = handler(job)
            # Final cancel check
            if self.is_cancel_requested(job.job_id):
                return self.store.update_job(
                    job.job_id,
                    status=DatasetJobStatus.CANCELLED,
                    finished_at=utc_now(),
                    error="cancelled",
                    result=result or {},
                    worker_pid=None,
                )
            return self.store.update_job(
                job.job_id,
                status=DatasetJobStatus.COMPLETED,
                progress=1.0,
                phase="done",
                result=result or {},
                finished_at=utc_now(),
                worker_pid=None,
            )
        except Exception as exc:  # noqa: BLE001
            if self.is_cancel_requested(job.job_id) or getattr(exc, "code", None) == "cancelled":
                return self.store.update_job(
                    job.job_id,
                    status=DatasetJobStatus.CANCELLED,
                    error="cancelled",
                    finished_at=utc_now(),
                    worker_pid=None,
                )
            if getattr(exc, "code", None) == "shard_interrupted":
                return self.store.update_job(
                    job.job_id,
                    status=DatasetJobStatus.INTERRUPTED,
                    error="interrupted — resume from verified shard checkpoint",
                    phase="interrupted",
                    finished_at=utc_now(),
                    worker_pid=None,
                )
            err = redact_secrets(f"{exc}\n{traceback.format_exc()}")
            return self.store.update_job(
                job.job_id,
                status=DatasetJobStatus.FAILED,
                error=err[:4000],
                finished_at=utc_now(),
                worker_pid=None,
            )

    def drain(self, *, max_jobs: int = 100) -> list[DatasetJob]:
        done: list[DatasetJob] = []
        for _ in range(max_jobs):
            job = self.process_next()
            if job is None:
                break
            done.append(job)
        return done

    def start_background(self, *, poll_seconds: float = 0.5) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()

            def _loop() -> None:
                while not self._stop.is_set():
                    job = self.process_next()
                    if job is None:
                        self._stop.wait(poll_seconds)

            self._thread = threading.Thread(target=_loop, name="dataset-jobs", daemon=True)
            self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None
