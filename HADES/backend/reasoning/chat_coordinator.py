"""Chat execution coordinator — orchestrates existing owners; does not reimplement them.

Maps BackendExecutionState events onto measurable ChatStages. Incremental extraction
target for send_message; characterization tests must pass before further moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatStage(str, Enum):
    RECEIVED = "RECEIVED"
    UNDERSTOOD = "UNDERSTOOD"
    CONTEXT_READY = "CONTEXT_READY"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ChatRunContext:
    """Thin alias over request identity + stage — wraps existing truth objects."""

    request_id: str
    conversation_id: str | None = None
    stage: ChatStage = ChatStage.RECEIVED
    route: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    cancel_requested: bool = False

    def advance(self, stage: ChatStage, **note: Any) -> ChatStage:
        if self.cancel_requested and stage not in {ChatStage.CANCELLED, ChatStage.FAILED}:
            self.stage = ChatStage.CANCELLED
            self.notes.append("advance_blocked_by_cancel")
            return self.stage
        self.stage = stage
        if note:
            self.notes.append(f"{stage.value}:{note}")
        return self.stage

    def request_cancel(self) -> None:
        self.cancel_requested = True
        self.stage = ChatStage.CANCELLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "stage": self.stage.value,
            "route": self.route,
            "notes": list(self.notes),
            "cancel_requested": self.cancel_requested,
        }


@dataclass
class ChatRunResult:
    context: ChatRunContext
    content: str = ""
    status: str = "running"
    execution_truth: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "content": self.content,
            "status": self.status,
            "execution_truth": self.execution_truth,
            "verification": self.verification,
        }


def emit_stage(execution_state: Any, context: ChatRunContext, stage: ChatStage, **payload: Any) -> None:
    """Bridge ChatStage → BackendExecutionState.emit when available."""
    context.advance(stage, **payload)
    emit = getattr(execution_state, "emit", None)
    if callable(emit):
        emit(f"CHAT_STAGE_{stage.value}", stage=stage.value, **payload)


def bind_understanding(context: ChatRunContext, *, spec: Any, route: Any) -> None:
    context.advance(ChatStage.UNDERSTOOD)
    context.route = {
        "kind": getattr(spec, "kind", None),
        "speech_act": getattr(spec, "speech_act", None),
        "needs_tools": getattr(spec, "needs_tools", None),
        "target": getattr(route, "target", None),
        "allow_tools": getattr(route, "allow_tools", None),
        "profile": getattr(route, "profile", None),
    }


# Stage order for characterization / invariant tests
STAGE_ORDER = [
    ChatStage.RECEIVED,
    ChatStage.UNDERSTOOD,
    ChatStage.CONTEXT_READY,
    ChatStage.PLANNED,
    ChatStage.EXECUTING,
    ChatStage.VERIFYING,
    ChatStage.FINALIZING,
    ChatStage.COMPLETED,
]
