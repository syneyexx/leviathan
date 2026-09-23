"""Canonical cognitive runtime types — public orchestration metadata only.

No private chain-of-thought is stored or exposed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EpistemicType(str, Enum):
    EXACT_FACT = "EXACT_FACT"
    KNOWLEDGE_SOURCE = "KNOWLEDGE_SOURCE"
    EVIDENCE = "EVIDENCE"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    NEURAL_ASSOCIATION = "NEURAL_ASSOCIATION"
    USER_STATEMENT = "USER_STATEMENT"
    SYSTEM_STATE = "SYSTEM_STATE"


class CognitiveRunStatus(str, Enum):
    CREATED = "CREATED"
    PERCEIVING = "PERCEIVING"
    REASONING = "REASONING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    CRITIQUING = "CRITIQUING"
    VERIFYING = "VERIFYING"
    REPLANNING = "REPLANNING"
    BLOCKED = "BLOCKED"
    COMPLETED_VERIFIED = "COMPLETED_VERIFIED"
    COMPLETED_UNVERIFIED = "COMPLETED_UNVERIFIED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    SHADOW = "SHADOW"


TERMINAL_STATUSES: frozenset[CognitiveRunStatus] = frozenset(
    {
        CognitiveRunStatus.COMPLETED_VERIFIED,
        CognitiveRunStatus.COMPLETED_UNVERIFIED,
        CognitiveRunStatus.PARTIAL,
        CognitiveRunStatus.FAILED,
        CognitiveRunStatus.CANCELLED,
        CognitiveRunStatus.TIMEOUT,
        CognitiveRunStatus.RESOURCE_EXHAUSTED,
        CognitiveRunStatus.BLOCKED,
        CognitiveRunStatus.SHADOW,
    }
)


# Valid directed transitions (from → allowed to).
ALLOWED_TRANSITIONS: dict[CognitiveRunStatus, frozenset[CognitiveRunStatus]] = {
    CognitiveRunStatus.CREATED: frozenset(
        {
            CognitiveRunStatus.PERCEIVING,
            CognitiveRunStatus.REASONING,
            CognitiveRunStatus.SHADOW,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
        }
    ),
    CognitiveRunStatus.PERCEIVING: frozenset(
        {
            CognitiveRunStatus.REASONING,
            CognitiveRunStatus.SHADOW,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.RESOURCE_EXHAUSTED,
        }
    ),
    CognitiveRunStatus.REASONING: frozenset(
        {
            CognitiveRunStatus.EXECUTING,
            CognitiveRunStatus.WAITING_APPROVAL,
            CognitiveRunStatus.REPLANNING,
            CognitiveRunStatus.VERIFYING,
            CognitiveRunStatus.CRITIQUING,
            CognitiveRunStatus.SHADOW,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.BLOCKED,
            CognitiveRunStatus.RESOURCE_EXHAUSTED,
            CognitiveRunStatus.COMPLETED_UNVERIFIED,
            CognitiveRunStatus.PARTIAL,
        }
    ),
    CognitiveRunStatus.WAITING_APPROVAL: frozenset(
        {
            CognitiveRunStatus.EXECUTING,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.BLOCKED,
            CognitiveRunStatus.FAILED,
        }
    ),
    CognitiveRunStatus.EXECUTING: frozenset(
        {
            CognitiveRunStatus.OBSERVING,
            CognitiveRunStatus.WAITING_APPROVAL,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.TIMEOUT,
            CognitiveRunStatus.RESOURCE_EXHAUSTED,
        }
    ),
    CognitiveRunStatus.OBSERVING: frozenset(
        {
            CognitiveRunStatus.CRITIQUING,
            CognitiveRunStatus.REASONING,
            CognitiveRunStatus.REPLANNING,
            CognitiveRunStatus.VERIFYING,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
        }
    ),
    CognitiveRunStatus.CRITIQUING: frozenset(
        {
            CognitiveRunStatus.REASONING,
            CognitiveRunStatus.REPLANNING,
            CognitiveRunStatus.VERIFYING,
            CognitiveRunStatus.EXECUTING,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.PARTIAL,
            CognitiveRunStatus.RESOURCE_EXHAUSTED,
        }
    ),
    CognitiveRunStatus.VERIFYING: frozenset(
        {
            CognitiveRunStatus.COMPLETED_VERIFIED,
            CognitiveRunStatus.COMPLETED_UNVERIFIED,
            CognitiveRunStatus.REPLANNING,
            CognitiveRunStatus.PARTIAL,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.CANCELLED,
        }
    ),
    CognitiveRunStatus.REPLANNING: frozenset(
        {
            CognitiveRunStatus.REASONING,
            CognitiveRunStatus.PERCEIVING,
            CognitiveRunStatus.CANCELLED,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.RESOURCE_EXHAUSTED,
            CognitiveRunStatus.PARTIAL,
        }
    ),
    CognitiveRunStatus.BLOCKED: frozenset(),
    CognitiveRunStatus.COMPLETED_VERIFIED: frozenset(),
    CognitiveRunStatus.COMPLETED_UNVERIFIED: frozenset(),
    CognitiveRunStatus.PARTIAL: frozenset(),
    CognitiveRunStatus.FAILED: frozenset(),
    CognitiveRunStatus.CANCELLED: frozenset(),
    CognitiveRunStatus.TIMEOUT: frozenset(),
    CognitiveRunStatus.RESOURCE_EXHAUSTED: frozenset(),
    CognitiveRunStatus.SHADOW: frozenset(),
}


class ReasoningMode(str, Enum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"
    MAXIMUM = "MAXIMUM"
    ADAPTIVE = "ADAPTIVE"


class ReasoningStrategy(str, Enum):
    DIRECT = "DIRECT"
    RETRIEVE_THEN_ANSWER = "RETRIEVE_THEN_ANSWER"
    PLAN_EXECUTE_VERIFY = "PLAN_EXECUTE_VERIFY"
    HYPOTHESIS_TEST = "HYPOTHESIS_TEST"
    DEBUG_LOOP = "DEBUG_LOOP"
    RESEARCH_SYNTHESIS = "RESEARCH_SYNTHESIS"
    CODING_REPAIR = "CODING_REPAIR"
    TOOL_DRIVEN = "TOOL_DRIVEN"
    MULTI_AGENT = "MULTI_AGENT"
    COMPARE_ALTERNATIVES = "COMPARE_ALTERNATIVES"
    HIGH_RISK_VERIFY = "HIGH_RISK_VERIFY"


class CognitiveActionKind(str, Enum):
    RESPOND = "RESPOND"
    RETRIEVE = "RETRIEVE"
    MODEL_CALL = "MODEL_CALL"
    SEARCH_CAPABILITY = "SEARCH_CAPABILITY"
    INVOKE_CAPABILITY = "INVOKE_CAPABILITY"
    DELEGATE_AGENT = "DELEGATE_AGENT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    WAIT = "WAIT"
    VERIFY = "VERIFY"
    REPLAN = "REPLAN"
    ASK_USER = "ASK_USER"
    FAIL = "FAIL"
    COMPLETE = "COMPLETE"


class CognitiveObservationKind(str, Enum):
    MODEL_RESULT = "MODEL_RESULT"
    RETRIEVAL_RESULT = "RETRIEVAL_RESULT"
    TOOL_RESULT = "TOOL_RESULT"
    AGENT_RESULT = "AGENT_RESULT"
    APPROVAL_RESULT = "APPROVAL_RESULT"
    SYSTEM_STATE = "SYSTEM_STATE"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    VERIFICATION_RESULT = "VERIFICATION_RESULT"
    USER_STEERING = "USER_STEERING"


class BeliefCategory(str, Enum):
    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"
    CONTRADICTION = "CONTRADICTION"


class BeliefStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INFERRED = "INFERRED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    REJECTED = "REJECTED"


class RiskClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class CognitiveBudgets:
    max_wall_time_seconds: float = 120.0
    max_model_calls: int = 4
    max_model_tokens: int = 8000
    max_tool_calls: int = 8
    max_agent_delegations: int = 2
    max_replans: int = 3
    max_retries: int = 3
    max_retrieval_rounds: int = 3
    max_parallel_workers: int = 2
    max_context_tokens: int = 6000
    max_critic_passes: int = 2
    max_iterations: int = 8

    def public_dict(self) -> dict[str, Any]:
        return {
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_model_calls": self.max_model_calls,
            "max_model_tokens": self.max_model_tokens,
            "max_tool_calls": self.max_tool_calls,
            "max_agent_delegations": self.max_agent_delegations,
            "max_replans": self.max_replans,
            "max_retries": self.max_retries,
            "max_retrieval_rounds": self.max_retrieval_rounds,
            "max_parallel_workers": self.max_parallel_workers,
            "max_context_tokens": self.max_context_tokens,
            "max_critic_passes": self.max_critic_passes,
            "max_iterations": self.max_iterations,
        }


@dataclass
class BudgetUsage:
    model_calls: int = 0
    model_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    agent_delegations: int = 0
    replans: int = 0
    retries: int = 0
    retrieval_rounds: int = 0
    critic_passes: int = 0
    iterations: int = 0
    started_monotonic: float = 0.0
    # "provider" when usage came from the model API; "estimate" when heuristic;
    # "unavailable" when nothing measured.
    token_usage_source: str = "unavailable"

    def public_dict(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "model_tokens": self.model_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
            "agent_delegations": self.agent_delegations,
            "replans": self.replans,
            "retries": self.retries,
            "retrieval_rounds": self.retrieval_rounds,
            "critic_passes": self.critic_passes,
            "iterations": self.iterations,
            "token_usage_source": self.token_usage_source,
            "truth": {
                "estimate_is_not_provider_usage": self.token_usage_source != "provider",
            },
        }


@dataclass(frozen=True)
class CognitiveAction:
    kind: CognitiveActionKind
    action_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    capability_id: str | None = None
    rationale: str | None = None  # public orchestration note, not CoT
    expected_observation: str | None = None
    risk_class: RiskClass = RiskClass.LOW
    requires_approval: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "action_id": self.action_id,
            "arguments": self.arguments,
            "capability_id": self.capability_id,
            "rationale": self.rationale,
            "expected_observation": self.expected_observation,
            "risk_class": self.risk_class.value,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True)
class CognitiveObservation:
    kind: CognitiveObservationKind
    observation_id: str
    summary: str
    source_type: EpistemicType = EpistemicType.SYSTEM_STATE
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    success: bool | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "observation_id": self.observation_id,
            "summary": self.summary,
            "source_type": self.source_type.value,
            "payload": self.payload,
            "evidence_refs": list(self.evidence_refs),
            "artifact_refs": list(self.artifact_refs),
            "success": self.success,
            "error": self.error,
            "truth": {
                "tool_output_is_untrusted_data": True,
                "observation_is_not_evidence": True,
            },
        }


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    objective: str
    dependencies: tuple[str, ...] = ()
    expected_observation: str | None = None
    acceptance_condition: str | None = None
    likely_capabilities: tuple[str, ...] = ()
    risk_class: RiskClass = RiskClass.LOW
    status: str = "PENDING"
    # Wave 1 structured plan extensions (U125)
    resource_estimate: dict[str, Any] = field(default_factory=dict)
    completion_criteria: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "objective": self.objective,
            "dependencies": list(self.dependencies),
            "expected_observation": self.expected_observation,
            "acceptance_condition": self.acceptance_condition,
            "likely_capabilities": list(self.likely_capabilities),
            "risk_class": self.risk_class.value,
            "status": self.status,
            "resource_estimate": dict(self.resource_estimate),
            "completion_criteria": list(self.completion_criteria),
        }


@dataclass
class CognitivePlan:
    plan_id: str
    strategy: ReasoningStrategy
    steps: list[PlanStep] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    stale: bool = False
    revision: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "strategy": self.strategy.value,
            "steps": [s.public_dict() for s in self.steps],
            "assumptions": list(self.assumptions),
            "stale": self.stale,
            "revision": self.revision,
        }


def validate_transition(current: CognitiveRunStatus, target: CognitiveRunStatus) -> bool:
    if current == target:
        return True
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    return target in allowed
