from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    REASONING_STARTED = "reasoning_started"
    REASONING_COMPLETED = "reasoning_completed"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    MODEL_STARTED = "model_started"
    MODEL_COMPLETED = "model_completed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    STATE_CHANGED = "state_changed"


from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    run_id: str
    event_type: EventType
    created_at: str
    payload: dict[str, Any]
