from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .states import JobState


@dataclass
class JobRecord:
    job_id: str
    capability_id: str
    arguments: dict[str, Any]
    state: JobState
    created_at: str
    updated_at: str
    run_id: str | None = None
    approval_id: str | None = None
    requested_by: str = "api"
    result: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Wave 0 durable kernel (U005 / U006 / U010 / U017)
    trace_id: str | None = None
    idempotency_key: str | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    last_heartbeat_at: str | None = None
    attempt_number: int = 1
    budget: dict[str, Any] = field(default_factory=dict)
    latency_class: str = "background"
    # Execution fabric additive fields
    domain: str | None = None
    consumer: str | None = None
    correlation_id: str | None = None
    root_job_id: str | None = None
    parent_job_id: str | None = None
    domain_entity_type: str | None = None
    domain_entity_id: str | None = None
    worker_pool: str | None = None
    resource_class: str | None = None
    priority: int = 100
    queued_at: str | None = None
    claimed_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    max_attempts: int = 3
    next_attempt_at: str | None = None
    timeout_seconds: float | None = None
    deadline_at: str | None = None
    cancel_requested_at: str | None = None
    cancel_reason: str | None = None
    progress: float | None = None
    phase: str | None = None
    message: str | None = None
    resource_request: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] | None = None
    artifact_refs: list[Any] = field(default_factory=list)
    error_code: str | None = None
    retryable: bool | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "capability_id": self.capability_id,
            "arguments": self.arguments,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
            "approval_id": self.approval_id,
            "requested_by": self.requested_by,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "trace_id": self.trace_id,
            "idempotency_key": self.idempotency_key,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "attempt_number": self.attempt_number,
            "budget": self.budget,
            "latency_class": self.latency_class,
            "domain": self.domain,
            "consumer": self.consumer,
            "correlation_id": self.correlation_id,
            "root_job_id": self.root_job_id,
            "parent_job_id": self.parent_job_id,
            "domain_entity_type": self.domain_entity_type,
            "domain_entity_id": self.domain_entity_id,
            "worker_pool": self.worker_pool,
            "resource_class": self.resource_class,
            "priority": self.priority,
            "queued_at": self.queued_at,
            "claimed_at": self.claimed_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "max_attempts": self.max_attempts,
            "next_attempt_at": self.next_attempt_at,
            "timeout_seconds": self.timeout_seconds,
            "deadline_at": self.deadline_at,
            "cancel_requested_at": self.cancel_requested_at,
            "cancel_reason": self.cancel_reason,
            "progress": self.progress,
            "phase": self.phase,
            "message": self.message,
            "resource_request": self.resource_request,
            "result_summary": self.result_summary,
            "artifact_refs": self.artifact_refs,
            "error_code": self.error_code,
            "retryable": self.retryable,
        }
