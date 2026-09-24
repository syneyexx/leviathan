from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_ALLOWED: dict[JobState, set[JobState]] = {
    JobState.CREATED: {JobState.QUEUED, JobState.CANCELLED},
    JobState.QUEUED: {JobState.RUNNING, JobState.CANCELLED},
    JobState.RUNNING: {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCEL_REQUESTED,
        JobState.RETRY_WAIT,
    },
    JobState.CANCEL_REQUESTED: {
        JobState.CANCELLED,
        JobState.FAILED,
        JobState.COMPLETED,
    },
    JobState.RETRY_WAIT: {JobState.QUEUED, JobState.CANCELLED, JobState.RUNNING},
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


class InvalidJobTransition(ValueError):
    pass


def validate_job_transition(current: JobState, new: JobState) -> None:
    if new not in _ALLOWED.get(current, set()):
        raise InvalidJobTransition(f"Illegal job transition {current.value} → {new.value}")


TERMINAL_JOB_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED})
