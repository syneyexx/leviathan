"""Canonical correlation / trace identity for cross-subsystem reconstruction.

U017: one correlation model across chat message, run, job, capability call,
agent node, artifact and evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def new_id(prefix: str = "") -> str:
    raw = str(uuid.uuid4())
    return f"{prefix}{raw}" if prefix else raw


@dataclass(frozen=True)
class CorrelationIds:
    """Stable identity bundle linking one execution chain.

    Missing fields are explicit ``None`` — never fabricate linkage.
    """

    trace_id: str
    run_id: str | None = None
    job_id: str | None = None
    request_id: str | None = None
    conversation_id: str | None = None
    agent_node_id: str | None = None
    parent_event_id: str | None = None
    idempotency_key: str | None = None

    @classmethod
    def create(
        cls,
        *,
        trace_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        request_id: str | None = None,
        conversation_id: str | None = None,
        agent_node_id: str | None = None,
        parent_event_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> CorrelationIds:
        return cls(
            trace_id=trace_id or new_id("tr_"),
            run_id=run_id,
            job_id=job_id,
            request_id=request_id,
            conversation_id=conversation_id,
            agent_node_id=agent_node_id,
            parent_event_id=parent_event_id,
            idempotency_key=idempotency_key,
        )

    def with_updates(self, **kwargs: Any) -> CorrelationIds:
        data = self.public_dict()
        data.update({k: v for k, v in kwargs.items() if k in data})
        return CorrelationIds(
            trace_id=str(data["trace_id"]),
            run_id=data.get("run_id"),
            job_id=data.get("job_id"),
            request_id=data.get("request_id"),
            conversation_id=data.get("conversation_id"),
            agent_node_id=data.get("agent_node_id"),
            parent_event_id=data.get("parent_event_id"),
            idempotency_key=data.get("idempotency_key"),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "agent_node_id": self.agent_node_id,
            "parent_event_id": self.parent_event_id,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class TraceContext:
    """Mutable request-scoped correlation carrier (not durable truth)."""

    ids: CorrelationIds = field(default_factory=CorrelationIds.create)

    def bind_run(self, run_id: str) -> CorrelationIds:
        self.ids = self.ids.with_updates(run_id=run_id)
        return self.ids

    def bind_job(self, job_id: str) -> CorrelationIds:
        self.ids = self.ids.with_updates(job_id=job_id)
        return self.ids

    def public_dict(self) -> dict[str, Any]:
        return self.ids.public_dict()
