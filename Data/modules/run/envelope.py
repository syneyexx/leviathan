"""Versioned internal event envelope (U003).

Every durable subsystem should emit events compatible with this schema.
Domain-specific EventType values remain in ``run.events``; this envelope is
the cross-cutting wire/persistence shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

EVENT_ENVELOPE_SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class EventEnvelope:
    """Canonical durable event shape across Run / Job / Cognition / Capabilities."""

    event_id: str
    event_type: str
    timestamp: str
    schema_version: int = EVENT_ENVELOPE_SCHEMA_VERSION
    trace_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    actor: str | None = None
    causal_parent: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        actor: str | None = None,
        causal_parent: str | None = None,
        artifact_refs: tuple[str, ...] | list[str] | None = None,
        evidence_refs: tuple[str, ...] | list[str] | None = None,
        event_id: str | None = None,
        timestamp: str | None = None,
        schema_version: int = EVENT_ENVELOPE_SCHEMA_VERSION,
    ) -> EventEnvelope:
        if schema_version != EVENT_ENVELOPE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported event envelope schema_version={schema_version}; "
                f"expected {EVENT_ENVELOPE_SCHEMA_VERSION}"
            )
        return cls(
            event_id=event_id or str(uuid.uuid4()),
            event_type=event_type,
            timestamp=timestamp or _utc_now(),
            schema_version=schema_version,
            trace_id=trace_id,
            run_id=run_id,
            job_id=job_id,
            actor=actor,
            causal_parent=causal_parent,
            payload=dict(payload or {}),
            artifact_refs=tuple(artifact_refs or ()),
            evidence_refs=tuple(evidence_refs or ()),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "actor": self.actor,
            "causal_parent": self.causal_parent,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "payload": self.payload,
            "artifact_refs": list(self.artifact_refs),
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        version = int(data.get("schema_version", EVENT_ENVELOPE_SCHEMA_VERSION))
        if version != EVENT_ENVELOPE_SCHEMA_VERSION:
            raise ValueError(f"WORKER_VERSION_MISMATCH: event schema_version={version}")
        return cls.create(
            str(data["event_type"]),
            event_id=str(data["event_id"]),
            timestamp=str(data["timestamp"]),
            schema_version=version,
            trace_id=data.get("trace_id"),
            run_id=data.get("run_id"),
            job_id=data.get("job_id"),
            actor=data.get("actor"),
            causal_parent=data.get("causal_parent"),
            payload=dict(data.get("payload") or {}),
            artifact_refs=tuple(data.get("artifact_refs") or ()),
            evidence_refs=tuple(data.get("evidence_refs") or ()),
        )
