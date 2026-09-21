from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrainingJobStatus(str, Enum):
    REGISTERED = "REGISTERED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TrainingJob:
    """Training job registry stub — no fake training progress."""

    job_id: str
    name: str
    status: TrainingJobStatus
    objective: str
    created_at: str
    updated_at: str
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status.value,
            "objective": self.objective,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metrics": self.metrics,
            "error": self.error,
            "truth": {
                "registered_is_not_trained": True,
                "no_fabricated_metrics": True,
            },
        }
