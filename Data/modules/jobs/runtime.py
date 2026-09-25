from __future__ import annotations

import threading
import uuid
from typing import Any

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway

from .resources import ResourceManager
from .retry import DEFAULT_RETRY_POLICY, RetryPolicy
from .states import TERMINAL_JOB_STATES, JobState
from .store import JobStore
from .types import JobRecord

# Capabilities owned by dedicated external/domain workers — API JobRuntime must not steal them.
EXTERNAL_WORKER_CAPABILITIES: frozenset[str] = frozenset(
    {
        "source_ingestion.process",
        "source_ingestion.brain_retry",
        "coding.advance",
        "research.advance",
        "research.plan",
        "research.retrieve",
        "research.synthesize",
        "research.verify",
        "dataset.process",
        "workflow.advance",
        "schedule.tick",
        "knowledge.prepare",
        "knowledge.commit",
        "knowledge.ingest_scan",
        "knowledge.ingest_document",
        "knowledge.ingest_path",
        "embedding.batch",
        "rerank.batch",
        "evaluation.run",
        "training.control",
        "market_sim.advance",
        "market_sim.gym_episode",
        "market_sim.research_campaign",
        "market_sim.news.poll",
        "backup.create",
        "maintenance.reconcile",
        "agent.advance",
        "agent_signal.deliver",
        "agent_signal.retry",
        "agent_signal.housekeeping",
        "provider.http",
        "provider.chat.complete",
        "provider.chat.stream",
        "provider.market.fetch",
        "provider.market.stream",
        "provider.market.stream.stop",
        "market_sim.scan_batch",
        "provider.alpaca.paper",
        "provider.hf.list",
        "model_download.start",
        "mcp.call",
        "research.fetch_url",
        "research.report.generate",
    }
)

_LOCAL_WORKER_ID = "job-runtime-local"


class JobRuntime:
    """Enqueue and execute capability jobs through the Execution Gateway.

    Jobs are durable in JobStore. Execution is synchronous on ``process_next`` /
    ``run_until_idle`` with a ResourceManager concurrency ceiling.

    ``start_background_worker`` remains for tests and in-process API demos; production
    frontier workers should claim via JobStore leases rather than this thread.
    """

    def __init__(
        self,
        store: JobStore,
        gateway: ExecutionGateway,
        resources: ResourceManager,
        *,
        retry_policy: RetryPolicy | None = None,
        worker_id: str = _LOCAL_WORKER_ID,
        lease_ttl_seconds: float = 60.0,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.resources = resources
        self.retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self.worker_id = worker_id
        self.lease_ttl_seconds = float(lease_ttl_seconds)
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
            "retries_scheduled": 0,
            "leases_recovered": 0,
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
        domain: str | None = None,
        consumer: str | None = None,
        correlation_id: str | None = None,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        domain_entity_type: str | None = None,
        domain_entity_id: str | None = None,
        worker_pool: str | None = None,
        resource_class: str | None = None,
        priority: int | None = None,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
        deadline_at: str | None = None,
    ) -> JobRecord:
        if self.gateway.get_capability(capability_id) is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        if idempotency_key:
            existing = self.store.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                self.telemetry["idempotent_hits"] = int(self.telemetry.get("idempotent_hits", 0)) + 1
                return existing
        resolved_pool = worker_pool
        if not resolved_pool:
            try:
                from Data.modules.workers.pools import pool_for_capability

                resolved_pool = pool_for_capability(capability_id)
            except Exception:  # noqa: BLE001
                resolved_pool = None
        create_kwargs: dict[str, Any] = {
            "capability_id": capability_id,
            "arguments": arguments,
            "run_id": run_id,
            "approval_id": approval_id,
            "requested_by": requested_by,
            "metadata": metadata,
            "trace_id": trace_id,
            "idempotency_key": idempotency_key,
            "budget": budget,
            "latency_class": latency_class,
            "domain": domain,
            "consumer": consumer,
            "correlation_id": correlation_id,
            "parent_job_id": parent_job_id,
            "root_job_id": root_job_id,
            "domain_entity_type": domain_entity_type,
            "domain_entity_id": domain_entity_id,
            "worker_pool": resolved_pool,
            "resource_class": resource_class,
            "priority": priority,
            "timeout_seconds": timeout_seconds,
            "deadline_at": deadline_at,
        }
        if max_attempts is not None:
            create_kwargs["max_attempts"] = max_attempts
        else:
            create_kwargs["max_attempts"] = self.retry_policy.max_attempts
        job = self.store.create(**create_kwargs)
        if job.state == JobState.CREATED:
            job = self.store.transition(job.job_id, JobState.QUEUED)
            self._cancel_flags[job.job_id] = threading.Event()
            self.telemetry["enqueued"] += 1
            self._wake.set()
            try:
                from Data.modules.workers.events import get_worker_event_emitter

                get_worker_event_emitter().job_queued(
                    job_id=job.job_id,
                    capability_id=capability_id,
                    pool=resolved_pool,
                    domain=domain,
                    metadata=metadata,
                    arguments=arguments,
                )
            except Exception:  # noqa: BLE001 — observability must not break enqueue
                pass
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self.store.get(job_id)

    def list(self, *, state: JobState | None = None, limit: int = 100) -> list[JobRecord]:
        return self.store.list(state=state, limit=limit)

    def cancel(self, job_id: str, *, reason: str | None = None) -> JobRecord:
        """Cancel a job: QUEUED/RETRY_WAIT → CANCELLED; RUNNING → CANCEL_REQUESTED."""
        job = self.store.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        if job.state in TERMINAL_JOB_STATES:
            raise ValueError(f"Job already terminal: {job.state.value}")
        flag = self._cancel_flags.get(job_id)
        if flag is not None:
            flag.set()
        try:
            job = self.store.request_cancel(job_id, reason=reason or "Cancelled by request")
        except ValueError:
            refreshed = self.store.get(job_id)
            if refreshed is None or refreshed.state not in TERMINAL_JOB_STATES:
                raise
            return refreshed
        if job.state == JobState.CANCELLED:
            self.telemetry["cancelled"] += 1
        return job

    def request_cancel(self, job_id: str, *, reason: str | None = None) -> JobRecord:
        """Alias for :meth:`cancel` (cooperative cancel path)."""
        return self.cancel(job_id, reason=reason)

    def process_next(self) -> JobRecord | None:
        """Claim and execute one queued job if a resource slot is free."""
        self.recover_expired_leases()
        reservation = f"reserve:{uuid.uuid4()}"
        if not self.resources.try_acquire(reservation):
            return None
        try:
            job = self.store.claim_next_queued(
                worker_id=self.worker_id,
                lease_ttl_seconds=self.lease_ttl_seconds,
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

    def recover_expired_leases(self) -> list[JobRecord]:
        recovered = self.store.recover_expired_leases()
        if recovered:
            self.telemetry["leases_recovered"] = int(self.telemetry.get("leases_recovered", 0)) + len(
                recovered
            )
            self._wake.set()
        return recovered

    def run_until_idle(self, *, max_jobs: int = 100) -> list[JobRecord]:
        done: list[JobRecord] = []
        for _ in range(max_jobs):
            result = self.process_next()
            if result is None:
                break
            done.append(result)
        return done

    def start_background_worker(self, *, poll_interval_s: float = 0.25) -> None:
        """In-process poll loop for tests/demos — not the production frontier worker."""
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
            self.recover_expired_leases()
            processed = self.process_next()
            if processed is None:
                self._wake.wait(timeout=poll_interval_s)
                self._wake.clear()

    def _cancel_requested(self, job_id: str, cancel_flag: threading.Event) -> bool:
        if cancel_flag.is_set():
            return True
        current = self.store.get(job_id)
        return current is not None and current.state == JobState.CANCEL_REQUESTED

    def _finalize_cancel(
        self,
        job_id: str,
        *,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> JobRecord:
        current = self.store.get(job_id)
        if current is None:
            raise KeyError(f"Unknown job: {job_id}")
        if current.state == JobState.CANCEL_REQUESTED:
            record = self.store.ack_cancel(job_id, result=result, error=error)
        elif current.state in TERMINAL_JOB_STATES:
            record = current
        else:
            # Still RUNNING but cancel flag set — request then ack.
            self.store.request_cancel(job_id, reason=error)
            record = self.store.ack_cancel(job_id, result=result, error=error)
        self.telemetry["cancelled"] += 1
        return record

    def _execute_claimed(self, job: JobRecord) -> JobRecord:
        self.telemetry["processed"] += 1
        cancel_flag = self._cancel_flags.setdefault(job.job_id, threading.Event())
        try:
            if self._cancel_requested(job.job_id, cancel_flag):
                return self._finalize_cancel(job.job_id, error="Cancelled before execution")

            # Lease already attached by claim_next_queued; refresh heartbeat.
            try:
                self.store.heartbeat_lease(
                    job.job_id,
                    worker_id=self.worker_id,
                    ttl_seconds=self.lease_ttl_seconds,
                )
            except ValueError:
                self.store.acquire_lease(
                    job.job_id,
                    worker_id=self.worker_id,
                    ttl_seconds=self.lease_ttl_seconds,
                )

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
            if self._cancel_requested(job.job_id, cancel_flag):
                return self._finalize_cancel(
                    job.job_id,
                    error="Cancelled during execution",
                    result=cap_result.public_dict(),
                )

            if cap_result.status == CapabilityStatus.COMPLETED:
                record = self.store.transition(
                    job.job_id,
                    JobState.COMPLETED,
                    result=cap_result.public_dict(),
                )
                self.telemetry["completed"] += 1
                return record

            error_text = cap_result.error or cap_result.status.value
            error_code = cap_result.status.value
            retryable = self.retry_policy.classify_retryable(
                error_text,
                error_code=error_code,
            )
            # Policy rejects and cancellations are never retried.
            if cap_result.status in {CapabilityStatus.REJECTED, CapabilityStatus.CANCELLED}:
                retryable = False
            if cap_result.status == CapabilityStatus.TIMEOUT:
                retryable = True

            refreshed = self.store.get(job.job_id) or job
            max_attempts = refreshed.max_attempts or self.retry_policy.max_attempts
            if retryable and refreshed.attempt_number < max_attempts:
                delay = self.retry_policy.delay_for_attempt(refreshed.attempt_number)
                record = self.store.schedule_retry(
                    job.job_id,
                    delay_seconds=delay,
                    error=error_text,
                    error_code=error_code,
                    retryable=True,
                )
                self.telemetry["retries_scheduled"] = (
                    int(self.telemetry.get("retries_scheduled", 0)) + 1
                )
                return record

            record = self.store.transition(
                job.job_id,
                JobState.FAILED,
                result=cap_result.public_dict(),
                error=error_text,
                error_code=error_code,
                retryable=retryable,
            )
            self.telemetry["failed"] += 1
            return record
        except Exception as exc:  # noqa: BLE001
            refreshed = self.store.get(job.job_id) or job
            retryable = self.retry_policy.classify_retryable(exc)
            max_attempts = refreshed.max_attempts or self.retry_policy.max_attempts
            if retryable and refreshed.attempt_number < max_attempts:
                delay = self.retry_policy.delay_for_attempt(refreshed.attempt_number)
                record = self.store.schedule_retry(
                    job.job_id,
                    delay_seconds=delay,
                    error=str(exc),
                    error_code=type(exc).__name__,
                    retryable=True,
                )
                self.telemetry["retries_scheduled"] = (
                    int(self.telemetry.get("retries_scheduled", 0)) + 1
                )
                return record
            record = self.store.transition(
                job.job_id,
                JobState.FAILED,
                error=str(exc),
                error_code=type(exc).__name__,
                retryable=retryable,
            )
            self.telemetry["failed"] += 1
            return record
        finally:
            try:
                self.store.release_lease(job.job_id, worker_id=self.worker_id)
            except Exception:  # noqa: BLE001
                pass
            self.resources.release(job.job_id)
            current = self.store.get(job.job_id)
            if current is None or current.state in TERMINAL_JOB_STATES or current.state == JobState.RETRY_WAIT:
                self._cancel_flags.pop(job.job_id, None)
