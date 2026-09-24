from __future__ import annotations

import threading
import uuid
from typing import Any

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway

from .resources import ResourceManager
from .states import TERMINAL_JOB_STATES, JobState
from .store import JobStore
from .types import JobRecord

# Capabilities owned by dedicated external/domain workers — API JobRuntime must not steal them.
EXTERNAL_WORKER_CAPABILITIES: frozenset[str] = frozenset(
    {
        "source_ingestion.process",
        "source_ingestion.brain_retry",
        "coding.advance",
    }
)


class JobRuntime:
    """Enqueue and execute capability jobs through the Execution Gateway.

    Jobs are durable in JobStore. Execution is synchronous on ``process_next`` /
    ``run_until_idle`` with a ResourceManager concurrency ceiling. A background
    worker thread can be started for API-driven async processing.
    """

    def __init__(
        self,
        store: JobStore,
        gateway: ExecutionGateway,
        resources: ResourceManager,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.resources = resources
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._wake = threading.Event()
        self.telemetry: dict[str, Any] = {
            "enqueued": 0,
            "processed": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }

    def enqueue(
        self,
        *,
        capability_id: str,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        approval_id: str | None = None,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        budget: dict[str, Any] | None = None,
        latency_class: str = "background",
    ) -> JobRecord:
        if self.gateway.get_capability(capability_id) is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        if idempotency_key:
            existing = self.store.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                self.telemetry["idempotent_hits"] = int(self.telemetry.get("idempotent_hits", 0)) + 1
                return existing
        job = self.store.create(
            capability_id=capability_id,
            arguments=arguments,
            run_id=run_id,
            approval_id=approval_id,
            requested_by=requested_by,
            metadata=metadata,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            budget=budget,
            latency_class=latency_class,
        )
        if job.state == JobState.CREATED:
            job = self.store.transition(job.job_id, JobState.QUEUED)
            self._cancel_flags[job.job_id] = threading.Event()
            self.telemetry["enqueued"] += 1
            self._wake.set()
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self.store.get(job_id)

    def list(self, *, state: JobState | None = None, limit: int = 100) -> list[JobRecord]:
        return self.store.list(state=state, limit=limit)

    def cancel(self, job_id: str) -> JobRecord:
        job = self.store.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        if job.state in TERMINAL_JOB_STATES:
            raise ValueError(f"Job already terminal: {job.state.value}")
        flag = self._cancel_flags.get(job_id)
        if flag is not None:
            flag.set()
        if job.state == JobState.RUNNING:
            # Cooperative: mark cancel request; process loop finalizes if still running.
            # If worker already finished, transition may race — re-read.
            try:
                job = self.store.transition(
                    job_id,
                    JobState.CANCELLED,
                    error="Cancelled by request",
                )
            except ValueError:
                refreshed = self.store.get(job_id)
                if refreshed is None or refreshed.state not in TERMINAL_JOB_STATES:
                    raise
                return refreshed
        else:
            job = self.store.transition(job_id, JobState.CANCELLED, error="Cancelled by request")
        self.telemetry["cancelled"] += 1
        return job

    def process_next(self) -> JobRecord | None:
        """Claim and execute one queued job if a resource slot is free."""
        reservation = f"reserve:{uuid.uuid4()}"
        if not self.resources.try_acquire(reservation):
            return None
        try:
            job = self.store.claim_next_queued(
                exclude_capability_ids=EXTERNAL_WORKER_CAPABILITIES,
            )
            if job is None:
                return None
            self.resources.rebind(reservation, job.job_id)
            reservation = ""  # ownership transferred; do not release below
            return self._execute_claimed(job)
        finally:
            if reservation:
                self.resources.release(reservation)

    def run_until_idle(self, *, max_jobs: int = 100) -> list[JobRecord]:
        done: list[JobRecord] = []
        for _ in range(max_jobs):
            result = self.process_next()
            if result is None:
                break
            done.append(result)
        return done

    def start_background_worker(self, *, poll_interval_s: float = 0.25) -> None:
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._worker_stop.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                args=(poll_interval_s,),
                name="leviathan-job-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def stop_background_worker(self, *, timeout: float = 2.0) -> None:
        self._worker_stop.set()
        self._wake.set()
        thread = self._worker_thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def _worker_loop(self, poll_interval_s: float) -> None:
        while not self._worker_stop.is_set():
            processed = self.process_next()
            if processed is None:
                self._wake.wait(timeout=poll_interval_s)
                self._wake.clear()

    def _execute_claimed(self, job: JobRecord) -> JobRecord:
        self.telemetry["processed"] += 1
        cancel_flag = self._cancel_flags.setdefault(job.job_id, threading.Event())
        try:
            if cancel_flag.is_set():
                record = self.store.transition(
                    job.job_id,
                    JobState.CANCELLED,
                    error="Cancelled before execution",
                )
                self.telemetry["cancelled"] += 1
                return record

            # Lease the in-process worker slot so expired remote claims are detectable.
            self.store.acquire_lease(job.job_id, worker_id="job-runtime-local", ttl_seconds=60.0)
            cap_result = self.gateway.execute(
                CapabilityRequest(
                    capability_id=job.capability_id,
                    arguments=job.arguments,
                    approval_id=job.approval_id,
                    run_id=job.run_id,
                    job_id=job.job_id,
                    requested_by=job.requested_by,
                    request_id=job.job_id,
                    trace_id=job.trace_id,
                    idempotency_key=job.idempotency_key,
                )
            )

            # Re-check cancel after gateway (cooperative).
            current = self.store.get(job.job_id)
            if current is not None and current.state == JobState.CANCELLED:
                self.telemetry["cancelled"] += 1
                return current

            if cancel_flag.is_set():
                record = self.store.transition(
                    job.job_id,
                    JobState.CANCELLED,
                    error="Cancelled during execution",
                    result=cap_result.public_dict(),
                )
                self.telemetry["cancelled"] += 1
                return record

            if cap_result.status == CapabilityStatus.COMPLETED:
                record = self.store.transition(
                    job.job_id,
                    JobState.COMPLETED,
                    result=cap_result.public_dict(),
                )
                self.telemetry["completed"] += 1
                return record

            record = self.store.transition(
                job.job_id,
                JobState.FAILED,
                result=cap_result.public_dict(),
                error=cap_result.error or cap_result.status.value,
            )
            self.telemetry["failed"] += 1
            return record
        except Exception as exc:  # noqa: BLE001
            record = self.store.transition(job.job_id, JobState.FAILED, error=str(exc))
            self.telemetry["failed"] += 1
            return record
        finally:
            try:
                self.store.release_lease(job.job_id, worker_id="job-runtime-local")
            except Exception:  # noqa: BLE001
                pass
            self.resources.release(job.job_id)
            self._cancel_flags.pop(job.job_id, None)
