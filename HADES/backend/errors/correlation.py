"""Correlation / run identity helpers for end-to-end tracing."""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CorrelationContext:
    trace_id: str
    run_id: str | None = None
    request_id: str | None = None
    agent_id: str | None = None
    task_id: str | None = None
    tool_call_id: str | None = None
    native_job_id: str | None = None

    def child(self, **overrides: Any) -> "CorrelationContext":
        data = {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "tool_call_id": self.tool_call_id,
            "native_job_id": self.native_job_id,
        }
        data.update({k: v for k, v in overrides.items() if v is not None})
        return CorrelationContext(**data)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v}


_current: contextvars.ContextVar[CorrelationContext | None] = contextvars.ContextVar(
    "hades_correlation", default=None
)


def new_trace_id() -> str:
    return str(uuid.uuid4())


def new_id(prefix: str = "") -> str:
    value = str(uuid.uuid4())
    return f"{prefix}{value}" if prefix else value


def start_correlation(
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    agent_id: str | None = None,
    task_id: str | None = None,
) -> CorrelationContext:
    ctx = CorrelationContext(
        trace_id=trace_id or new_trace_id(),
        run_id=run_id,
        request_id=request_id or new_id("req-"),
        agent_id=agent_id,
        task_id=task_id,
    )
    _current.set(ctx)
    return ctx


def get_correlation() -> CorrelationContext | None:
    return _current.get()


def bind_correlation(ctx: CorrelationContext | None) -> contextvars.Token:
    return _current.set(ctx)


def reset_correlation(token: contextvars.Token) -> None:
    _current.reset(token)


def ensure_correlation(**kwargs: Any) -> CorrelationContext:
    existing = get_correlation()
    if existing is None:
        return start_correlation(**kwargs)
    if kwargs:
        updated = existing.child(**kwargs)
        _current.set(updated)
        return updated
    return existing
