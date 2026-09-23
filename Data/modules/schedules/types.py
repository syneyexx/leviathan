from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"


class ScheduleTargetKind(str, Enum):
    WORKFLOW = "WORKFLOW"
    JOB = "JOB"
    EVENT = "EVENT"  # Wave 11: event-triggered enqueue into Jobs/Workflows


@dataclass(frozen=True)
class ScheduleRecord:
    schedule_id: str
    name: str
    status: ScheduleStatus
    target_kind: ScheduleTargetKind
    target_ref: str  # workflow template name or capability_id for jobs
    interval_seconds: int
    created_at: str
    updated_at: str
    next_run_at: str
    last_run_at: str | None = None
    target_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "status": self.status.value,
            "target_kind": self.target_kind.value,
            "target_ref": self.target_ref,
            "interval_seconds": self.interval_seconds,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "target_payload": self.target_payload,
            "metadata": self.metadata,
        }
