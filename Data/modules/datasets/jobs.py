"""Background dataset jobs with cancel and interrupt reconcile.

Claim ownership
---------------
* **Legacy / tests** (no JobRuntime): ``DatasetJobRunner`` claims from
  ``dataset_jobs`` via ``claim_next_queued``.
* **Externalized** (``LEVIATHAN_DATASET_JOBS_RUNNER=external``): the Job Kernel
  owns the runnable claim (``dataset.process`` / pool ``dataset``). Domain rows
  remain metadata; the worker claims a kernel job then CAS-claims the linked
  domain row by id. Only one active claim loop may run — never start the
  in-process domain runner alongside an external dataset worker.
"""

from __future__ import annotations

import os
import threading
import traceback
import uuid
from typing import TYPE_CHECKING, Any, Callable

from Data.modules.common.process import pid_is_alive

from Data.modules.common.secrets import redact_secrets

from .store import DatasetStore, utc_now
from .types import (
    CAPABILITY_PROCESS,
    DOMAIN_ENTITY_TYPE,
    KERNEL_IDEMPOTENCY_PREFIX,
    WORKER_POOL,
    DatasetJob,
    DatasetJobStatus,
)

if TYPE_CHECKING:
    from Data.modules.jobs.runtime import JobRuntime
    from Data.modules.jobs.types import JobRecord


JobHandler = Callable[[DatasetJob], dict[str, Any]]


class DatasetJobRunner:
    """Worker for dataset_jobs with cancel/interrupt reconciliation.

    When ``job_runtime`` is set, ``process_next`` claims Job Kernel leases for
    ``dataset.process`` and then executes the linked domain job — domain
    ``claim_next_queued`` is not used (avoids double claim under external mode).
    """

    def __init__(
        self,
        store: DatasetStore,
        handlers: dict[str, JobHandler],
        *,
        job_runtime: JobRuntime | None = None,
        worker_id: str | None = None,
        lease_ttl_seconds: float = 120.0,
    ) -> None:
        self.store = store
        self.handlers = handlers
        self.jobs = job_runtime
        self.worker_id = worker_id or f"dataset-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.lease_ttl_seconds = float(lease_ttl_seconds)
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
        if self.jobs is not None:
            return self._process_next_kernel()
        return self._process_next_domain()

    def process_kernel_job(self, kernel_job: JobRecord) -> DatasetJob | None:
        """Execute a kernel job already claimed by the pool loop / worker."""
        domain_id = self._domain_id_from_kernel(kernel_job)
        if not domain_id:
            self._fail_kernel(kernel_job, "missing domain_entity_id / dataset_job_id")
            return None
        return self._execute_linked_domain(kernel_job, domain_id)

    def _process_next_kernel(self) -> DatasetJob | None:
        assert self.jobs is not None
        from Data.modules.jobs.states import JobState

        store = self.jobs.store
        if hasattr(store, "claim_next_for_pool"):
            kernel_job = store.claim_next_for_pool(
                pool_id=WORKER_POOL,
                worker_id=self.worker_id,
                lease_ttl_seconds=self.lease_ttl_seconds,
                capability_ids={CAPABILITY_PROCESS},
            )
        else:
            kernel_job = store.claim_next_queued(
                worker_id=self.worker_id,
                lease_ttl_seconds=self.lease_ttl_seconds,
                capability_ids={CAPABILITY_PROCESS},
                worker_pool=WORKER_POOL,
            )
        if kernel_job is None:
            return None
        try:
            if kernel_job.state == JobState.CANCEL_REQUESTED:
                store.ack_cancel(kernel_job.job_id)
                return None
            return self.process_kernel_job(kernel_job)
        finally:
            try:
                store.release_lease(kernel_job.job_id, worker_id=self.worker_id)
            except Exception:  # noqa: BLE001
                pass

    def _process_next_domain(self) -> DatasetJob | None:
        job = self.store.claim_next_queued()
        if job is None:
            return None
        return self._run_domain_job(job)

    def _execute_linked_domain(self, kernel_job: JobRecord, domain_id: str) -> DatasetJob | None:
        assert self.jobs is not None
        domain = self.store.get_job(domain_id)
        if domain is None:
            self._fail_kernel(kernel_job, f"domain job not found: {domain_id}")
            return None

        if domain.status == DatasetJobStatus.QUEUED:
            if domain.cancel_requested:
                domain = self.store.update_job(
                    domain_id,
                    status=DatasetJobStatus.CANCELLED,
                    finished_at=utc_now(),
                    error="cancelled",
                    worker_pid=None,
                )
            else:
                claimed = self.store.claim_queued_job(domain_id)
                if claimed is None:
                    domain = self.store.get_job(domain_id)
                    if domain is None:
                        self._fail_kernel(kernel_job, f"domain claim lost: {domain_id}")
                        return None
                else:
                    domain = claimed

        if domain.status in {
            DatasetJobStatus.COMPLETED,
            DatasetJobStatus.FAILED,
            DatasetJobStatus.CANCELLED,
            DatasetJobStatus.INTERRUPTED,
        }:
            self._mirror_domain_to_kernel(kernel_job, domain)
            return domain

        if domain.cancel_requested:
            cancelled = self.store.update_job(
                domain_id,
                status=DatasetJobStatus.CANCELLED,
                finished_at=utc_now(),
                error="cancelled",
                worker_pid=None,
            )
            self._mirror_domain_to_kernel(kernel_job, cancelled)
            return cancelled

        if domain.status != DatasetJobStatus.RUNNING:
            self._fail_kernel(
                kernel_job,
                f"domain job not runnable: {domain.status.value}",
            )
            return domain

        done = self._run_domain_job(domain)
        self._mirror_domain_to_kernel(kernel_job, done)
        return done

    def _run_domain_job(self, job: DatasetJob) -> DatasetJob:
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

    def _mirror_domain_to_kernel(self, kernel_job: JobRecord, domain: DatasetJob) -> None:
        from Data.modules.jobs.states import JobState

        assert self.jobs is not None
        mapping = {
            DatasetJobStatus.COMPLETED: JobState.COMPLETED,
            DatasetJobStatus.FAILED: JobState.FAILED,
            DatasetJobStatus.CANCELLED: JobState.CANCELLED,
            DatasetJobStatus.INTERRUPTED: JobState.FAILED,
        }
        target = mapping.get(domain.status)
        if target is None:
            return
        try:
            self.jobs.store.transition(
                kernel_job.job_id,
                target,
                result={
                    "dataset_job_id": domain.job_id,
                    "status": domain.status.value,
                    "job_type": domain.job_type.value,
                    "result": domain.result or {},
                },
                error=domain.error,
                error_code="DATASET_INTERRUPTED"
                if domain.status == DatasetJobStatus.INTERRUPTED
                else None,
            )
        except Exception:  # noqa: BLE001
            pass

    def _fail_kernel(self, kernel_job: JobRecord, error: str) -> None:
        from Data.modules.jobs.states import JobState

        if self.jobs is None:
            return
        try:
            self.jobs.store.transition(
                kernel_job.job_id,
                JobState.FAILED,
                error=error[:500],
                error_code="DATASET_LINK_ERROR",
                retryable=False,
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _domain_id_from_kernel(kernel_job: JobRecord) -> str | None:
        entity = getattr(kernel_job, "domain_entity_id", None)
        if entity:
            return str(entity)
        args = getattr(kernel_job, "arguments", None) or {}
        for key in ("dataset_job_id", "job_id", "domain_entity_id"):
            value = args.get(key)
            if value:
                return str(value)
        return None

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


def kernel_idempotency_key(domain_job_id: str) -> str:
    return f"{KERNEL_IDEMPOTENCY_PREFIX}{domain_job_id}"


def enqueue_kernel_for_domain_job(
    job_runtime: JobRuntime,
    domain_job: DatasetJob,
) -> JobRecord | None:
    """Enqueue (or reuse) a Job Kernel lease linked to a domain dataset job."""
    try:
        return job_runtime.enqueue(
            capability_id=CAPABILITY_PROCESS,
            arguments={
                "dataset_job_id": domain_job.job_id,
                "job_type": domain_job.job_type.value,
                "dataset_id": domain_job.dataset_id,
                "version_id": domain_job.version_id,
            },
            requested_by="datasets",
            idempotency_key=kernel_idempotency_key(domain_job.job_id),
            metadata={
                "dataset_job_id": domain_job.job_id,
                "job_type": domain_job.job_type.value,
            },
            latency_class="background",
            domain="datasets",
            domain_entity_type=DOMAIN_ENTITY_TYPE,
            domain_entity_id=domain_job.job_id,
            worker_pool=WORKER_POOL,
            resource_class="IO_HEAVY",
        )
    except Exception:  # noqa: BLE001 — domain queue must remain usable without kernel
        return None
