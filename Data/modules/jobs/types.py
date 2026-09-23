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
        }
