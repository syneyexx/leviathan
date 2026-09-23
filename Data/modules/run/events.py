from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    REASONING_STARTED = "reasoning_started"
    REASONING_COMPLETED = "reasoning_completed"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    MODEL_STARTED = "model_started"
    MODEL_COMPLETED = "model_completed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    STATE_CHANGED = "state_changed"
    # Wave 0 durable kernel
    LEASE_ACQUIRED = "lease_acquired"
    LEASE_HEARTBEAT = "lease_heartbeat"
    LEASE_EXPIRED = "lease_expired"
    LEASE_TAKEOVER = "lease_takeover"
    CHECKPOINT_SAVED = "checkpoint_saved"
    IDEMPOTENT_REPLAY = "idempotent_replay"


from dataclasses import dataclass, field
from typing import Any

from .envelope import EVENT_ENVELOPE_SCHEMA_VERSION, EventEnvelope


@dataclass(frozen=True)
class EventRecord:
    """Persisted run event. Prefer ``to_envelope`` for cross-subsystem correlation."""

    event_id: str
    run_id: str
    event_type: EventType
    created_at: str
    payload: dict[str, Any]
    trace_id: str | None = None
    job_id: str | None = None
    actor: str | None = None
    causal_parent: str | None = None
    schema_version: int = EVENT_ENVELOPE_SCHEMA_VERSION
    artifact_refs: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def to_envelope(self) -> EventEnvelope:
        return EventEnvelope.create(
            self.event_type.value,
            event_id=self.event_id,
            timestamp=self.created_at,
            schema_version=self.schema_version,
            trace_id=self.trace_id,
            run_id=self.run_id,
            job_id=self.job_id,
            actor=self.actor,
            causal_parent=self.causal_parent,
            payload=self.payload,
            artifact_refs=self.artifact_refs,
            evidence_refs=self.evidence_refs,
        )

    def public_dict(self) -> dict[str, Any]:
        return self.to_envelope().public_dict()
