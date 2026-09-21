from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .states import RunState


@dataclass
class RunRecord:
    run_id: str
    conversation_id: str | None
    parent_run_id: str | None
    user_request: str
    state: RunState
    intent: str | None
    complexity: str | None
    selected_model: str | None
    created_at: str
    updated_at: str
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "parent_run_id": self.parent_run_id,
            "user_request": self.user_request,
            "state": self.state.value,
            "intent": self.intent,
            "complexity": self.complexity,
            "selected_model": self.selected_model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }
