"""Phase 12: continual-learning safety lifecycle.

Explicit experience states. Raw model text is never durable training input.
LEARN remains disabled by default on NeuralRuntimeBoundary / ModelGateway.

HADES
  Candidate Experience
    -> Verification
    -> Accepted OR Rejected
  Accepted
    -> Training Eligible
    -> Fast Memory (bounded)
    -> Consolidation Candidate
    -> Slow Memory Candidate
    -> Evaluation
    -> Promote OR Reject
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from neural.errors import NeuralError, NeuralModeUnsupported
from neural.experience import (
    ExperienceOutcome,
    NeuralExperience,
    RewardLabel,
    contains_personal_data,
    contains_secret_material,
    experience_text_blob,
)


class LearningLifecycleError(NeuralError):
    code = "neural_learning_lifecycle_error"


class ExperienceLifecycleState(str, Enum):
    CANDIDATE = "candidate_experience"
    VERIFICATION = "verification"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TRAINING_ELIGIBLE = "training_eligible"
    FAST_MEMORY = "fast_memory"
    CONSOLIDATION_CANDIDATE = "consolidation_candidate"
    SLOW_MEMORY_CANDIDATE = "slow_memory_candidate"
    EVALUATION = "evaluation"
    PROMOTED = "promoted"
    PROMOTION_REJECTED = "promotion_rejected"


# Allowed directed transitions (fail closed otherwise).
_ALLOWED: dict[ExperienceLifecycleState, frozenset[ExperienceLifecycleState]] = {
    ExperienceLifecycleState.CANDIDATE: frozenset(
        {ExperienceLifecycleState.VERIFICATION, ExperienceLifecycleState.REJECTED}
    ),
    ExperienceLifecycleState.VERIFICATION: frozenset(
        {
            ExperienceLifecycleState.ACCEPTED,
            ExperienceLifecycleState.REJECTED,
        }
    ),
    ExperienceLifecycleState.ACCEPTED: frozenset(
        {
            ExperienceLifecycleState.TRAINING_ELIGIBLE,
            ExperienceLifecycleState.REJECTED,
        }
    ),
    ExperienceLifecycleState.REJECTED: frozenset(),
    ExperienceLifecycleState.TRAINING_ELIGIBLE: frozenset(
        {
            ExperienceLifecycleState.FAST_MEMORY,
            ExperienceLifecycleState.CONSOLIDATION_CANDIDATE,
            ExperienceLifecycleState.REJECTED,
        }
    ),
    ExperienceLifecycleState.FAST_MEMORY: frozenset(
        {
            ExperienceLifecycleState.CONSOLIDATION_CANDIDATE,
            ExperienceLifecycleState.REJECTED,
        }
    ),
    ExperienceLifecycleState.CONSOLIDATION_CANDIDATE: frozenset(
        {
            ExperienceLifecycleState.SLOW_MEMORY_CANDIDATE,
            ExperienceLifecycleState.REJECTED,
        }
    ),
    ExperienceLifecycleState.SLOW_MEMORY_CANDIDATE: frozenset(
        {ExperienceLifecycleState.EVALUATION, ExperienceLifecycleState.REJECTED}
    ),
    ExperienceLifecycleState.EVALUATION: frozenset(
        {
            ExperienceLifecycleState.PROMOTED,
            ExperienceLifecycleState.PROMOTION_REJECTED,
        }
    ),
    ExperienceLifecycleState.PROMOTED: frozenset(),
    ExperienceLifecycleState.PROMOTION_REJECTED: frozenset(),
}


@dataclass
class LifecycleRecord:
    experience_id: str
    state: ExperienceLifecycleState
    history: list[str] = field(default_factory=list)
    rejection_reason: str | None = None
    source_kind: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


def assert_learn_disabled_by_default(*, learn_enabled: bool = False) -> None:
    """Hard gate: production LEARN must remain off unless explicitly enabled later."""
    if learn_enabled:
        raise NeuralModeUnsupported(
            "unrestricted LEARN is not enabled; Phase 12 keeps LEARN disabled by default",
            detail={"learn_enabled": True},
        )


def reject_raw_model_output_for_training(
    *,
    source_kind: str,
    verified: bool,
    has_external_result: bool,
) -> str | None:
    """Return rejection reason when durable learning must not proceed.

    Bad: LLM says X -> write X permanently
    Required: external action/tool/test/evidence + verification
    """
    kind = (source_kind or "").strip().lower()
    if kind in {"raw_model_output", "completion", "assistant_message", "llm_text", "unverified_completion"}:
        return "raw_model_output_not_trainable"
    if not verified:
        return "verification_required"
    if not has_external_result:
        return "external_result_required"
    return None


class ExperienceLifecycle:
    """Fail-closed state machine for neural learning eligibility."""

    def __init__(self, experience_id: str, *, source_kind: str = "unknown") -> None:
        self.record = LifecycleRecord(
            experience_id=experience_id,
            state=ExperienceLifecycleState.CANDIDATE,
            history=[ExperienceLifecycleState.CANDIDATE.value],
            source_kind=source_kind,
        )

    @property
    def state(self) -> ExperienceLifecycleState:
        return self.record.state

    def transition(self, new_state: ExperienceLifecycleState, *, reason: str | None = None) -> LifecycleRecord:
        allowed = _ALLOWED.get(self.record.state, frozenset())
        if new_state not in allowed:
            raise LearningLifecycleError(
                "illegal experience lifecycle transition",
                detail={
                    "from": self.record.state.value,
                    "to": new_state.value,
                    "allowed": sorted(s.value for s in allowed),
                },
            )
        self.record.state = new_state
        self.record.history.append(new_state.value)
        if new_state in {
            ExperienceLifecycleState.REJECTED,
            ExperienceLifecycleState.PROMOTION_REJECTED,
        }:
            self.record.rejection_reason = reason or self.record.rejection_reason or "rejected"
        return self.record

    def admit_from_neural_experience(self, experience: NeuralExperience) -> LifecycleRecord:
        """Advance Candidate -> Verification -> Accepted/Rejected using Phase 6 gates."""
        assert_learn_disabled_by_default(learn_enabled=False)
        self.transition(ExperienceLifecycleState.VERIFICATION)
        raw_block = reject_raw_model_output_for_training(
            source_kind=experience.source,
            verified=bool(experience.verified),
            has_external_result=bool(experience.verification or experience.tools or experience.files),
        )
        if experience.contains_chain_of_thought:
            return self.transition(
                ExperienceLifecycleState.REJECTED,
                reason="hidden_reasoning_rejected",
            )
        if raw_block:
            return self.transition(ExperienceLifecycleState.REJECTED, reason=raw_block)
        blob = experience_text_blob(experience)
        if contains_secret_material(blob):
            return self.transition(
                ExperienceLifecycleState.REJECTED,
                reason="secret_material_rejected",
            )
        if contains_personal_data(blob):
            return self.transition(
                ExperienceLifecycleState.REJECTED,
                reason="personal_data_rejected",
            )
        if experience.reward.label is RewardLabel.INELIGIBLE:
            return self.transition(ExperienceLifecycleState.REJECTED, reason="reward_ineligible")
        if experience.outcome in {
            ExperienceOutcome.UNVERIFIED_SUCCESS,
            ExperienceOutcome.UNKNOWN,
            ExperienceOutcome.INCOMPLETE,
            ExperienceOutcome.PARTIAL,
            ExperienceOutcome.REJECTED,
            ExperienceOutcome.CANCELLED,
        }:
            return self.transition(
                ExperienceLifecycleState.REJECTED,
                reason=f"outcome_{experience.outcome.value}",
            )
        # Verified failure / blocked can be accepted as a negative experience
        # (avoidance signal), but never as positive success memory.
        self.transition(ExperienceLifecycleState.ACCEPTED)
        if experience.reward.label is RewardLabel.POSITIVE and experience.verified:
            return self.transition(ExperienceLifecycleState.TRAINING_ELIGIBLE)
        if experience.reward.label is RewardLabel.NEGATIVE and experience.outcome in {
            ExperienceOutcome.VERIFIED_FAILURE,
            ExperienceOutcome.BLOCKED,
        }:
            self.record.metadata["failure_memory"] = True
            self.record.metadata["negative_slow_eligible"] = True
            return self.transition(ExperienceLifecycleState.TRAINING_ELIGIBLE)
        return self.transition(ExperienceLifecycleState.REJECTED, reason="not_training_eligible")

    def mark_fast_memory_written(self) -> LifecycleRecord:
        if self.state is not ExperienceLifecycleState.TRAINING_ELIGIBLE:
            raise LearningLifecycleError(
                "fast memory requires training_eligible state",
                detail={"state": self.state.value},
            )
        return self.transition(ExperienceLifecycleState.FAST_MEMORY)

    def mark_consolidation_candidate(self) -> LifecycleRecord:
        if self.state not in {
            ExperienceLifecycleState.TRAINING_ELIGIBLE,
            ExperienceLifecycleState.FAST_MEMORY,
        }:
            raise LearningLifecycleError(
                "consolidation requires training_eligible or fast_memory",
                detail={"state": self.state.value},
            )
        return self.transition(ExperienceLifecycleState.CONSOLIDATION_CANDIDATE)

    def mark_slow_candidate(self) -> LifecycleRecord:
        return self.transition(ExperienceLifecycleState.SLOW_MEMORY_CANDIDATE)

    def mark_evaluation(self) -> LifecycleRecord:
        return self.transition(ExperienceLifecycleState.EVALUATION)

    def mark_promoted(self) -> LifecycleRecord:
        return self.transition(ExperienceLifecycleState.PROMOTED)

    def mark_promotion_rejected(self, reason: str) -> LifecycleRecord:
        return self.transition(ExperienceLifecycleState.PROMOTION_REJECTED, reason=reason)


def lifecycle_from_mapping(raw: Mapping[str, Any]) -> ExperienceLifecycle:
    life = ExperienceLifecycle(
        str(raw.get("experience_id") or "unknown"),
        source_kind=str(raw.get("source_kind") or "unknown"),
    )
    state = ExperienceLifecycleState(str(raw.get("state") or ExperienceLifecycleState.CANDIDATE.value))
    # Restore without replaying transitions (trusted internal snapshot only).
    life.record.state = state
    life.record.history = [str(x) for x in (raw.get("history") or [state.value])]
    life.record.rejection_reason = raw.get("rejection_reason")
    life.record.metadata = dict(raw.get("metadata") or {})
    return life
