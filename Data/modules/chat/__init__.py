"""LEVIATHAN Chat turn model — CONTROL-owned durable turn metadata + contracts.

Canonical owners remain elsewhere:
- CognitiveRuntime owns deep execution
- RunStore owns run lifecycle
- ActivityEmitter owns operational activity
- ArtifactStore owns artifacts
- Model Control Plane owns model selection

This package adds the ChatTurn abstraction and persistence references —
it does NOT create parallel retrieval, execution, or artifact authorities.
"""

from .cancellation import CancelReason, ChatCancelResult, cancel_chat_turn
from .cognition_stream import CognitionPublicSink, map_cognition_events_to_public_sink
from .coordinator import ChatTurnCoordinator
from .protocol import (
    STREAM_EVENT_TYPES,
    build_stream_meta,
    normalize_chat_response,
)
from .store import ChatTurnStore
from .types import (
    ChatTurn,
    ChatTurnRunState,
    ExecutionPath,
    FailureClassification,
    MeasurementValue,
    ResponseOwner,
    StreamingPosture,
    VerificationTurnState,
    new_turn_id,
)

__all__ = [
    "CancelReason",
    "ChatCancelResult",
    "ChatTurn",
    "ChatTurnCoordinator",
    "ChatTurnRunState",
    "ChatTurnStore",
    "CognitionPublicSink",
    "ExecutionPath",
    "FailureClassification",
    "MeasurementValue",
    "ResponseOwner",
    "STREAM_EVENT_TYPES",
    "StreamingPosture",
    "VerificationTurnState",
    "build_stream_meta",
    "cancel_chat_turn",
    "map_cognition_events_to_public_sink",
    "new_turn_id",
    "normalize_chat_response",
]
