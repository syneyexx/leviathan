"""Formal Chat Turn model — identity, execution ownership, measured telemetry."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ChatTurnRunState(str, Enum):
    """Durable turn acceptance / terminal state (orthogonal to RunStore RunState)."""

    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    STREAMING = "STREAMING"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Monotonic terminal states — once reached, may not leave (except INTERRUPTED→FAILED recovery).
TERMINAL_TURN_STATES: frozenset[ChatTurnRunState] = frozenset(
    {
        ChatTurnRunState.COMPLETED,
        ChatTurnRunState.FAILED,
        ChatTurnRunState.CANCELLED,
    }
)

ALLOWED_TURN_TRANSITIONS: dict[ChatTurnRunState, frozenset[ChatTurnRunState]] = {
    ChatTurnRunState.ACCEPTED: frozenset(
        {
            ChatTurnRunState.RUNNING,
            ChatTurnRunState.STREAMING,
            ChatTurnRunState.FAILED,
            ChatTurnRunState.CANCELLED,
            ChatTurnRunState.INTERRUPTED,
        }
    ),
    ChatTurnRunState.RUNNING: frozenset(
        {
            ChatTurnRunState.STREAMING,
            ChatTurnRunState.COMPLETED,
            ChatTurnRunState.FAILED,
            ChatTurnRunState.CANCELLED,
            ChatTurnRunState.INTERRUPTED,
        }
    ),
    ChatTurnRunState.STREAMING: frozenset(
        {
            ChatTurnRunState.COMPLETED,
            ChatTurnRunState.FAILED,
            ChatTurnRunState.CANCELLED,
            ChatTurnRunState.INTERRUPTED,
            ChatTurnRunState.RUNNING,  # degrade from streaming to buffered
        }
    ),
    ChatTurnRunState.INTERRUPTED: frozenset(
        {
            ChatTurnRunState.FAILED,
            ChatTurnRunState.CANCELLED,
            ChatTurnRunState.COMPLETED,  # reconciliation found authoritative completion
        }
    ),
    ChatTurnRunState.COMPLETED: frozenset(),
    ChatTurnRunState.FAILED: frozenset(),
    ChatTurnRunState.CANCELLED: frozenset(),
}


class InvalidTurnTransition(ValueError):
    pass


def validate_turn_transition(current: ChatTurnRunState, target: ChatTurnRunState) -> None:
    if current == target:
        return
    allowed = ALLOWED_TURN_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTurnTransition(f"Illegal ChatTurn transition: {current.value} → {target.value}")


class ResponseOwner(str, Enum):
    DIRECT = "direct"
    COGNITION = "cognition"
    TEAM = "team"
    UNKNOWN = "unknown"


class ExecutionPath(str, Enum):
    DIRECT_CHAT = "direct_chat"
    COGNITION_OWNED = "cognition_owned"
    COGNITION_SHADOW = "cognition_shadow"
    TEAM = "team"
    FALLBACK = "fallback"


class FailureClassification(str, Enum):
    NONE = "none"
    USER_CANCEL = "user_cancel"
    CLIENT_DISCONNECT = "client_disconnect"
    TIMEOUT = "timeout"
    PROVIDER_FAILURE = "provider_failure"
    BACKEND_FAILURE = "backend_failure"
    PROTOCOL_FAILURE = "protocol_failure"
    VALIDATION_ERROR = "validation_error"
    AUTHORIZATION_ERROR = "authorization_error"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class VerificationTurnState(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    FAILED = "FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class MeasurementState(str, Enum):
    MEASURED = "MEASURED"
    UNMEASURED = "UNMEASURED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class MeasurementValue:
    """Tri-state numeric measurement — absent must never collapse to zero."""

    state: MeasurementState
    value: float | int | None = None

    @classmethod
    def measured(cls, value: float | int) -> MeasurementValue:
        return cls(state=MeasurementState.MEASURED, value=value)

    @classmethod
    def unmeasured(cls) -> MeasurementValue:
        return cls(state=MeasurementState.UNMEASURED, value=None)

    @classmethod
    def unavailable(cls) -> MeasurementValue:
        return cls(state=MeasurementState.UNAVAILABLE, value=None)

    @classmethod
    def from_optional(cls, value: float | int | None, *, measured: bool = True) -> MeasurementValue:
        if value is None:
            return cls.unmeasured()
        if not measured:
            return cls.unmeasured()
        return cls.measured(value)

    def public_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "value": self.value}


@dataclass
class StreamingPosture:
    requested: bool = False
    effective: bool = False
    degraded: bool = False
    reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested_streaming": self.requested,
            "effective_streaming": self.effective,
            "streaming_degraded": self.degraded,
            "degrade_reason": self.reason,
        }


def new_turn_id() -> str:
    return str(uuid.uuid4())


@dataclass
class ChatTurn:
    """Durable Chat turn metadata — references canonical owners; no payload duplication."""

    turn_id: str
    conversation_id: str
    user_message_id: int | None = None
    assistant_message_id: int | None = None

    chat_run_id: str | None = None
    cognition_run_id: str | None = None
    team_run_id: str | None = None
    operation_id: str | None = None
    activity_run_id: str | None = None

    requested_model: str | None = None
    effective_model: str | None = None
    requested_reasoning_mode: str | None = None
    effective_reasoning_mode: str | None = None
    collaboration_strategy: str | None = None
    behavior_profile_id: str | None = None
    behavior_version: str | None = None
    behavior_hash: str | None = None

    response_owner: str = ResponseOwner.UNKNOWN.value
    execution_path: str = ExecutionPath.DIRECT_CHAT.value

    run_state: str = ChatTurnRunState.ACCEPTED.value
    streaming_effective: bool = False
    streaming_degraded: bool = False
    provisional: bool = False
    cancelled: bool = False
    failure_classification: str = FailureClassification.NONE.value

    # Retrieval — NULL means unmeasured (never coerce to 0 on read of absent).
    knowledge_hit_count: int | None = None
    memory_hit_count: int | None = None
    evidence_hit_count: int | None = None
    retrieval_coverage: float | None = None
    knowledge_available: bool | None = None
    retrieval_requested: bool | None = None

    verification_mode: str | None = None
    verification_state: str = VerificationTurnState.UNKNOWN.value
    quality_state: str | None = None

    tool_receipt_ids_json: str = "[]"
    decision_receipt_ids_json: str = "[]"
    artifact_ids_json: str = "[]"
    source_refs_json: str = "[]"
    activity_ref: str | None = None

    detected_language: str | None = None
    requested_language: str | None = None
    response_language: str | None = None

    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    latency_ms: float | None = None

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    context_used: int | None = None
    context_budget: int | None = None

    idempotency_key: str | None = None
    metadata_json: str = "{}"
    error_summary: str | None = None

    def public_dict(self) -> dict[str, Any]:
        import json

        data = asdict(self)
        # Surface measurement honesty for counts.
        data["retrieval"] = {
            "knowledge_hit_count": _measurement_public(self.knowledge_hit_count),
            "memory_hit_count": _measurement_public(self.memory_hit_count),
            "evidence_hit_count": _measurement_public(self.evidence_hit_count),
            "retrieval_coverage": _measurement_public(self.retrieval_coverage),
            "knowledge_available": self.knowledge_available,
            "retrieval_requested": self.retrieval_requested,
        }
        data["streaming"] = {
            "effective": self.streaming_effective,
            "degraded": self.streaming_degraded,
        }
        data["usage"] = {
            "input_tokens": _measurement_public(self.input_tokens),
            "output_tokens": _measurement_public(self.output_tokens),
            "total_tokens": _measurement_public(self.total_tokens),
            "context_used": _measurement_public(self.context_used),
            "context_budget": _measurement_public(self.context_budget),
            "latency_ms": _measurement_public(self.latency_ms),
        }
        # Parse JSON reference columns for frontend hydration (honest absence = []).
        data["tool_receipt_ids"] = _parse_json_list(self.tool_receipt_ids_json)
        data["decision_receipt_ids"] = _parse_json_list(self.decision_receipt_ids_json)
        data["artifact_ids"] = _parse_json_list(self.artifact_ids_json)
        data["source_refs"] = _parse_json_list(self.source_refs_json)
        meta = _parse_json_object(self.metadata_json)
        data["metadata"] = meta
        # Bounded tool_calls summary when persisted at complete (never invent).
        tool_calls = meta.get("tool_calls") if isinstance(meta, dict) else None
        if isinstance(tool_calls, list):
            data["tool_calls"] = tool_calls
        # Historic activity projection only when explicitly stored — never invent.
        activity = meta.get("activity") if isinstance(meta, dict) else None
        if isinstance(activity, dict):
            data["activity"] = activity
        return data


def _measurement_public(value: float | int | None) -> dict[str, Any]:
    if value is None:
        return MeasurementValue.unmeasured().public_dict()
    return MeasurementValue.measured(value).public_dict()


def _parse_json_list(raw: str | None) -> list[Any]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    import json

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# Frontend-aligned turn lifecycle (documented contract; mirrored in TS).
class FrontendTurnState(str, Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    STREAMING = "STREAMING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    DEGRADED = "DEGRADED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


FRONTEND_ALLOWED: dict[FrontendTurnState, frozenset[FrontendTurnState]] = {
    FrontendTurnState.IDLE: frozenset(
        {FrontendTurnState.PREPARING, FrontendTurnState.RUNNING}
    ),
    FrontendTurnState.PREPARING: frozenset(
        {
            FrontendTurnState.RUNNING,
            FrontendTurnState.STREAMING,
            FrontendTurnState.FAILED,
            FrontendTurnState.CANCELLED,
            FrontendTurnState.IDLE,
        }
    ),
    FrontendTurnState.RUNNING: frozenset(
        {
            FrontendTurnState.STREAMING,
            FrontendTurnState.CANCELLING,
            FrontendTurnState.COMPLETED,
            FrontendTurnState.FAILED,
            FrontendTurnState.CANCELLED,
            FrontendTurnState.DEGRADED,
        }
    ),
    FrontendTurnState.STREAMING: frozenset(
        {
            FrontendTurnState.CANCELLING,
            FrontendTurnState.COMPLETED,
            FrontendTurnState.FAILED,
            FrontendTurnState.CANCELLED,
            FrontendTurnState.DEGRADED,
        }
    ),
    FrontendTurnState.CANCELLING: frozenset(
        {
            FrontendTurnState.CANCELLED,
            FrontendTurnState.FAILED,
            FrontendTurnState.COMPLETED,  # race: completion wins before cancel ack
        }
    ),
    FrontendTurnState.DEGRADED: frozenset(
        {
            FrontendTurnState.COMPLETED,
            FrontendTurnState.FAILED,
            FrontendTurnState.CANCELLED,
            FrontendTurnState.CANCELLING,
        }
    ),
    FrontendTurnState.COMPLETED: frozenset({FrontendTurnState.IDLE}),
    FrontendTurnState.FAILED: frozenset({FrontendTurnState.IDLE}),
    FrontendTurnState.CANCELLED: frozenset({FrontendTurnState.IDLE}),
}
