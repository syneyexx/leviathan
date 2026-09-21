from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .types import TrainingJob, TrainingJobStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TrainingRegistry:
    """Register training intents without claiming training execution."""

    def __init__(self) -> None:
        self._jobs: dict[str, TrainingJob] = {}

    def list(self) -> list[TrainingJob]:
        return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def get(self, job_id: str) -> TrainingJob | None:
        return self._jobs.get(job_id)

    def register(self, *, name: str, objective: str) -> TrainingJob:
        now = utc_now()
        job = TrainingJob(
            job_id=str(uuid.uuid4()),
            name=name.strip() or "training",
            status=TrainingJobStatus.REGISTERED,
            objective=objective.strip() or "unspecified",
            created_at=now,
            updated_at=now,
            metrics={},
        )
        self._jobs[job.job_id] = job
        return job

    def mark_failed(self, job_id: str, error: str) -> TrainingJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        updated = TrainingJob(
            job_id=job.job_id,
            name=job.name,
            status=TrainingJobStatus.FAILED,
            objective=job.objective,
            created_at=job.created_at,
            updated_at=utc_now(),
            metrics=job.metrics,
            error=error,
        )
        self._jobs[job_id] = updated
        return updated

    def start_unsupported(self, job_id: str) -> TrainingJob:
        """Honest refusal: training execution is not implemented."""
        return self.mark_failed(
            job_id,
            "Training execution runtime is not implemented — registered only",
        )
