"""Coding Agent domain types — sessions, turns, steps, patches."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Mission(str, Enum):
    SCAFFOLD = "SCAFFOLD"
    REVIEW = "REVIEW"
    TEST = "TEST"
    FIX = "FIX"
    GENERIC = "GENERIC"


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    PARTIAL = "PARTIAL"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    CANCELLED = "CANCELLED"
    DISABLED = "DISABLED"


class StepKind(str, Enum):
    PLAN = "PLAN"
    CAPABILITY = "CAPABILITY"
    WAIT_APPROVAL = "WAIT_APPROVAL"
    VERIFY = "VERIFY"
    RESPOND = "RESPOND"
    CRITIC = "CRITIC"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"


TERMINAL_STATUSES = frozenset(
    {
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.UNVERIFIED,
        SessionStatus.PARTIAL,
        SessionStatus.RESOURCE_EXHAUSTED,
        SessionStatus.CANCELLED,
        SessionStatus.DISABLED,
    }
)

ACTIVE_STATUSES = frozenset(
    {
        SessionStatus.RUNNING,
        SessionStatus.WAITING_APPROVAL,
    }
)

DEFAULT_FEATURE_TRUTH = {
    "uses_shared_gateway": True,
    "no_private_execution": True,
    "hades_excluded": True,
}


class CodingError(Exception):
    """Domain error with HTTP-friendly public payload."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class CodingSession:
    session_id: str
    created_at: str
    updated_at: str
    mission: Mission
    status: SessionStatus
    workspace_root: str
    title: str = ""
    user_goal: str = ""
    conversation_id: str | None = None
    run_id: str | None = None
    model_id: str | None = None
    error: str | None = None
    verification_id: str | None = None
    feature_truth: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FEATURE_TRUTH))
    neuro: dict[str, Any] = field(default_factory=dict)
    pending_capability: dict[str, Any] | None = None
    cancel_requested: bool = False
    worker_pid: int | None = None
    round_count: int = 0
    read_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        cognition = dict(self.metadata.get("cognition") or {}) if isinstance(self.metadata, dict) else {}
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mission": self.mission.value,
            "status": self.status.value,
            "workspace_root": self.workspace_root,
            "title": self.title,
            "user_goal": self.user_goal,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "error": self.error,
            "verification_id": self.verification_id,
            "feature_truth": dict(self.feature_truth),
            "neuro": dict(self.neuro),
            "pending_capability": dict(self.pending_capability) if self.pending_capability else None,
            "cancel_requested": self.cancel_requested,
            "round_count": self.round_count,
            "read_paths": list(self.read_paths),
            "metadata": dict(self.metadata),
            "phase": cognition.get("phase"),
            "task_type": cognition.get("task_type"),
            "coding_role": cognition.get("role"),
            "plan": cognition.get("plan"),
            "brain_context": cognition.get("brain_context"),
            "acceptance": cognition.get("acceptance"),
            "hypotheses": cognition.get("hypotheses"),
            "truth": {
                "one_brain": True,
                "started_is_not_completed": True,
                "max_rounds_is_not_success": True,
                "unavailable_is_not_passed": True,
            },
        }


@dataclass
class CodingTurn:
    turn_id: str
    session_id: str
    seq: int
    role: str
    content: str
    created_at: str
    content_raw: str | None = None
    neuro_assessment: dict[str, Any] | None = None
    token_estimate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "seq": self.seq,
            "role": self.role,
            "content": self.content,
            "content_raw": self.content_raw,
            "created_at": self.created_at,
            "neuro_assessment": self.neuro_assessment,
            "token_estimate": self.token_estimate,
            "metadata": dict(self.metadata),
        }


@dataclass
class CodingStep:
    step_id: str
    session_id: str
    seq: int
    kind: StepKind
    status: StepStatus
    created_at: str
    updated_at: str
    turn_id: str | None = None
    capability_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None
    observation_id: str | None = None
    effect_id: str | None = None
    artifact_id: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    requested_by: str = "agent:coding"

    def public_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "seq": self.seq,
            "kind": self.kind.value,
            "capability_id": self.capability_id,
            "arguments": dict(self.arguments),
            "approval_id": self.approval_id,
            "status": self.status.value,
            "observation_id": self.observation_id,
            "effect_id": self.effect_id,
            "artifact_id": self.artifact_id,
            "output": dict(self.output),
            "error": self.error,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CodingPatch:
    patch_id: str
    session_id: str
    path: str
    diff_unified: str
    created_at: str
    artifact_id: str | None = None
    hash_before: str | None = None
    hash_after: str | None = None
    applied: bool = False
    approval_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "session_id": self.session_id,
            "artifact_id": self.artifact_id,
            "path": self.path,
            "diff_unified": self.diff_unified,
            "hash_before": self.hash_before,
            "hash_after": self.hash_after,
            "applied": self.applied,
            "approval_id": self.approval_id,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class ParsedCapability:
    capability_id: str
    arguments: dict[str, Any]
    raw: str = ""
    source: str = "xml"  # xml | json


@dataclass
class LoopResult:
    session: CodingSession
    status: SessionStatus
    rounds: int = 0
    error: str | None = None
    verification: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "session": self.session.public_dict(),
            "status": self.status.value,
            "rounds": self.rounds,
            "error": self.error,
            "verification": self.verification,
        }
