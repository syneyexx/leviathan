from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowState(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class WorkflowStepDef:
    step_id: str
    capability_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "arguments": self.arguments,
            "approval_id": self.approval_id,
        }


@dataclass
class WorkflowRecord:
    workflow_id: str
    name: str
    state: WorkflowState
    steps: list[WorkflowStepDef]
    created_at: str
    updated_at: str
    current_step: int = 0
    run_id: str | None = None
    step_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "state": self.state.value,
            "steps": [s.public_dict() for s in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_step": self.current_step,
            "run_id": self.run_id,
            "step_results": self.step_results,
            "error": self.error,
            "metadata": self.metadata,
        }
