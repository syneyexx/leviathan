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
        }
