"""LEVIATHAN Signal Fabric — typed enumerations and shared constants.

Signals are structured coordination envelopes. They are NOT chat messages,
NOT a second mission system, and NOT an authority bypass.
"""

from __future__ import annotations

from enum import Enum


class SignalType(str, Enum):
    """Canonical signal type vocabulary.

    Semantics (operational, not conversational):
      TASK_REQUEST / TASK_HANDOFF — request or transfer bounded work via AgentMission
      FINDING / EVIDENCE / HYPOTHESIS — structured observations; project to Blackboard
      QUESTION / ANSWER — clarification between participants
      ARTIFACT_READY — large output referenced by ID
      VERIFY_REQUEST / VERIFIED / REJECTED / CHALLENGE — evaluation workflow
      DECISION — orchestrator/agent decision record
      BLOCK / UNBLOCK / CANCEL — authority-gated control
      RESOURCE_REQUEST / WORKER_SPAWN_REQUEST — capacity asks (no free worker mesh)
      PROGRESS / WARNING / ERROR / HEARTBEAT — status / telemetry
      MEMORY_CANDIDATE / KNOWLEDGE_CANDIDATE — promotion candidates (not direct writes)
      COMPLETED — terminal coordination notice
    """

    TASK_REQUEST = "TASK_REQUEST"
    TASK_HANDOFF = "TASK_HANDOFF"
    FINDING = "FINDING"
    EVIDENCE = "EVIDENCE"
    HYPOTHESIS = "HYPOTHESIS"
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    ARTIFACT_READY = "ARTIFACT_READY"
    VERIFY_REQUEST = "VERIFY_REQUEST"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CHALLENGE = "CHALLENGE"
    DECISION = "DECISION"
    BLOCK = "BLOCK"
    UNBLOCK = "UNBLOCK"
    RESOURCE_REQUEST = "RESOURCE_REQUEST"
    WORKER_SPAWN_REQUEST = "WORKER_SPAWN_REQUEST"
    PROGRESS = "PROGRESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CANCEL = "CANCEL"
    MEMORY_CANDIDATE = "MEMORY_CANDIDATE"
    KNOWLEDGE_CANDIDATE = "KNOWLEDGE_CANDIDATE"
    HEARTBEAT = "HEARTBEAT"
    COMPLETED = "COMPLETED"


class SignalPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    TELEMETRY = "TELEMETRY"


# Lower integer = higher delivery urgency (matches JobStore priority ASC).
PRIORITY_RANK: dict[SignalPriority, int] = {
    SignalPriority.CRITICAL: 0,
    SignalPriority.HIGH: 10,
    SignalPriority.NORMAL: 50,
    SignalPriority.LOW: 80,
    SignalPriority.TELEMETRY: 100,
}


class RecipientType(str, Enum):
    AGENT = "AGENT"
    ORCHESTRATOR = "ORCHESTRATOR"
    ROLE = "ROLE"
    CAPABILITY = "CAPABILITY"
    MISSION = "MISSION"
    SYSTEM = "SYSTEM"
    # Controlled parent-worker mechanics only — never unrestricted worker mesh.
    WORKER = "WORKER"


class SenderType(str, Enum):
    AGENT = "AGENT"
    ORCHESTRATOR = "ORCHESTRATOR"
    SYSTEM = "SYSTEM"
    OPERATOR = "OPERATOR"
    WORKER = "WORKER"
    MISSION = "MISSION"


class SignalStatus(str, Enum):
    """Aggregate signal lifecycle (independent of per-delivery state)."""

    CREATED = "CREATED"
    ROUTED = "ROUTED"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    DEAD_LETTERED = "DEAD_LETTERED"


class DeliveryState(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONSUMED = "CONSUMED"
    FAILED = "FAILED"
    RETRY_WAIT = "RETRY_WAIT"
    DEAD_LETTER = "DEAD_LETTER"
    EXPIRED = "EXPIRED"


class RoutingMode(str, Enum):
    DIRECT = "DIRECT"
    ROLE = "ROLE"
    CAPABILITY = "CAPABILITY"
    ORCHESTRATOR = "ORCHESTRATOR"
    MISSION = "MISSION"
    SYSTEM = "SYSTEM"


# Signals that require explicit acknowledgement (not mere queue placement).
ACK_REQUIRED_TYPES: frozenset[SignalType] = frozenset(
    {
        SignalType.TASK_HANDOFF,
        SignalType.VERIFY_REQUEST,
        SignalType.BLOCK,
        SignalType.CANCEL,
    }
)

# Types that must never be discarded by telemetry coalescing.
CRITICAL_NEVER_DROP: frozenset[SignalType] = frozenset(
    {
        SignalType.BLOCK,
        SignalType.UNBLOCK,
        SignalType.CANCEL,
        SignalType.VERIFY_REQUEST,
        SignalType.VERIFIED,
        SignalType.REJECTED,
        SignalType.CHALLENGE,
        SignalType.TASK_REQUEST,
        SignalType.TASK_HANDOFF,
        SignalType.ERROR,
    }
)

# High-volume types eligible for coalescing / sampling.
TELEMETRY_TYPES: frozenset[SignalType] = frozenset(
    {
        SignalType.HEARTBEAT,
        SignalType.PROGRESS,
    }
)

# Blackboard projection map (signal type -> blackboard kind). Telemetry excluded.
BLACKBOARD_PROJECTION: dict[SignalType, str] = {
    SignalType.FINDING: "finding",
    SignalType.HYPOTHESIS: "hypothesis",
    SignalType.ARTIFACT_READY: "artifact",
    SignalType.QUESTION: "open_question",
    SignalType.DECISION: "decision",
    SignalType.EVIDENCE: "finding",
}

DEFAULT_MAX_HOPS = 8
DEFAULT_MAX_PAYLOAD_BYTES = 32_768
DEFAULT_MAX_REFS = 32
DEFAULT_MAX_SUBJECT_LEN = 500
DEFAULT_RETRY_ATTEMPTS = 5
DEFAULT_ACK_TIMEOUT_S = 300
DEFAULT_MISSION_SIGNAL_BUDGET = 500
DEFAULT_MAX_AGENT_ROUNDTRIPS = 64
DEFAULT_TELEMETRY_COALESCE_S = 5.0
DEFAULT_RETENTION_DAYS_CRITICAL = 90
DEFAULT_RETENTION_DAYS_NORMAL = 30
DEFAULT_RETENTION_DAYS_TELEMETRY = 3

# Machine-readable error codes (stable API contract).
SIGNAL_NOT_FOUND = "SIGNAL_NOT_FOUND"
SIGNAL_INVALID_RECIPIENT = "SIGNAL_INVALID_RECIPIENT"
SIGNAL_UNAUTHORIZED = "SIGNAL_UNAUTHORIZED"
SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
SIGNAL_MAX_HOPS = "SIGNAL_MAX_HOPS"
SIGNAL_BUDGET_EXCEEDED = "SIGNAL_BUDGET_EXCEEDED"
SIGNAL_NO_RECIPIENT = "SIGNAL_NO_RECIPIENT"
SIGNAL_DUPLICATE = "SIGNAL_DUPLICATE"
SIGNAL_DELIVERY_FAILED = "SIGNAL_DELIVERY_FAILED"
SIGNAL_DEAD_LETTERED = "SIGNAL_DEAD_LETTERED"
SIGNAL_FEATURE_OFF = "SIGNAL_FEATURE_OFF"
SIGNAL_INVALID_PAYLOAD = "SIGNAL_INVALID_PAYLOAD"
SIGNAL_WORKER_MESH_FORBIDDEN = "SIGNAL_WORKER_MESH_FORBIDDEN"
COMMUNICATION_BUDGET_EXCEEDED = "COMMUNICATION_BUDGET_EXCEEDED"
MAX_HOPS_EXCEEDED = "MAX_HOPS_EXCEEDED"
