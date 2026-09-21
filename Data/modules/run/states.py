from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    RETRIEVING = "RETRIEVING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


# Explicit allowed transitions. Impossible edges (e.g. FAILED → COMPLETED) are rejected.
ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset(
        {
            RunState.QUEUED,
            RunState.PLANNING,
            RunState.CANCELLED,
            RunState.BLOCKED,
            RunState.FAILED,
        }
    ),
    RunState.QUEUED: frozenset(
        {
            RunState.PLANNING,
            RunState.CANCELLED,
            RunState.BLOCKED,
            RunState.FAILED,
        }
    ),
    RunState.PLANNING: frozenset(
        {
            RunState.RETRIEVING,
            RunState.WAITING_FOR_APPROVAL,
            RunState.EXECUTING,
            RunState.VERIFYING,
            RunState.COMPLETED,
            RunState.PARTIAL,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.BLOCKED,
        }
    ),
    RunState.RETRIEVING: frozenset(
        {
            RunState.PLANNING,
            RunState.EXECUTING,
            RunState.WAITING_FOR_APPROVAL,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.BLOCKED,
        }
    ),
    RunState.WAITING_FOR_APPROVAL: frozenset(
        {
            RunState.EXECUTING,
            RunState.CANCELLED,
            RunState.BLOCKED,
            RunState.FAILED,
        }
    ),
    RunState.EXECUTING: frozenset(
        {
            RunState.VERIFYING,
            RunState.RETRIEVING,
            RunState.WAITING_FOR_APPROVAL,
            RunState.COMPLETED,
            RunState.PARTIAL,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.BLOCKED,
        }
    ),
    RunState.VERIFYING: frozenset(
        {
            RunState.COMPLETED,
            RunState.PARTIAL,
            RunState.FAILED,
            RunState.EXECUTING,
            RunState.RETRIEVING,
            RunState.CANCELLED,
            RunState.BLOCKED,
        }
    ),
    RunState.COMPLETED: frozenset(),
    RunState.PARTIAL: frozenset({RunState.EXECUTING, RunState.CANCELLED, RunState.FAILED}),
    RunState.FAILED: frozenset({RunState.QUEUED, RunState.PLANNING}),  # recovery = new attempt semantics
    RunState.CANCELLED: frozenset(),
    RunState.BLOCKED: frozenset({RunState.QUEUED, RunState.PLANNING, RunState.CANCELLED, RunState.FAILED}),
}


class InvalidRunTransition(ValueError):
    pass


def validate_transition(current: RunState, target: RunState) -> None:
    if current == target:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidRunTransition(f"Illegal Run transition: {current.value} → {target.value}")
