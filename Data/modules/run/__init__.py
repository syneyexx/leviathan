"""Canonical Run + Event model for non-trivial LEVIATHAN executions."""

from .envelope import EVENT_ENVELOPE_SCHEMA_VERSION, EventEnvelope
from .events import EventRecord, EventType
from .states import InvalidRunTransition, RunState, validate_transition
from .store import RunStore
from .types import RunRecord

__all__ = [
    "EVENT_ENVELOPE_SCHEMA_VERSION",
    "EventEnvelope",
    "EventRecord",
    "EventType",
    "InvalidRunTransition",
    "RunRecord",
    "RunState",
    "RunStore",
    "validate_transition",
]
