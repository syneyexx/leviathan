"""Phase 12 continual-learning orchestrator.

Connects verified experiences to Fast Memory and evaluate-then-promote Slow Memory
without enabling unrestricted online LEARN.

Task
  -> Verify
  -> Experience
  -> Eligibility (+ secret / personal-data gates)
  -> Fast Memory (bounded)
  -> Consolidation Candidate
  -> Evaluation
  -> Promote OR Reject / Rollback
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from neural.consolidation import ConsolidationPipeline, ConsolidationReport
from neural.encoding import SlowMemoryExample
from neural.errors import NeuralPersonalDataRejected, NeuralSecretRejected
from neural.experience import (
    ExperienceOutcome,
    NeuralExperience,
    RewardLabel,
    contains_personal_data,
    contains_secret_material,
    experience_text_blob,
)
from neural.fast_memory import FastMemorySession, FastWriteResult
from neural.learning_lifecycle import (
    ExperienceLifecycle,
    ExperienceLifecycleState,
    assert_learn_disabled_by_default,
)


@dataclass
class EligibilityDecision:
    eligible: bool
    reason: str
    fast_memory_eligible: bool = False
    consolidation_eligible: bool = False
    failure_memory: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContinualLearningResult:
    experience_id: str
    lifecycle_state: str
    eligibility: EligibilityDecision
    fast_write: dict[str, Any] | None = None
    consolidation: dict[str, Any] | None = None
    negative_slow_sample: dict[str, Any] | None = None
    rolled_back: bool = False
    base_unchanged: bool | None = None
    retention_before: float | None = None
    retention_after: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "lifecycle_state": self.lifecycle_state,
            "eligibility": self.eligibility.to_dict(),
            "fast_write": self.fast_write,
            "consolidation": self.consolidation,
            "negative_slow_sample": self.negative_slow_sample,
            "rolled_back": self.rolled_back,
            "base_unchanged": self.base_unchanged,
            "retention_before": self.retention_before,
            "retention_after": self.retention_after,
            "notes": list(self.notes),
        }


def evaluate_learning_eligibility(experience: NeuralExperience) -> EligibilityDecision:
    """Deterministic eligibility between capture and neural learning."""
    assert_learn_disabled_by_default(learn_enabled=False)
    blob = experience_text_blob(experience)

    if experience.contains_chain_of_thought:
        return EligibilityDecision(False, "hidden_reasoning_rejected")
    if experience.source in {
        "raw_model_output",
        "completion",
        "assistant_message",
        "llm_text",
        "unverified_completion",
    }:
        return EligibilityDecision(False, "raw_model_output_not_trainable")
    if contains_secret_material(blob):
        return EligibilityDecision(
            False,
            "secret_material_rejected",
            detail={"policy": "never_consolidate_secrets"},
        )
    if contains_personal_data(blob):
        return EligibilityDecision(
            False,
            "personal_data_rejected",
            detail={"policy": "prefer_exact_memory_for_personal_facts"},
        )
    if experience.reward.label is RewardLabel.INELIGIBLE:
        return EligibilityDecision(False, "reward_ineligible")
    # Positive verified success → fast + consolidation candidate.
    if (
        experience.verified
        and experience.reward.label is RewardLabel.POSITIVE
        and experience.reward.score > 0
        and experience.outcome is ExperienceOutcome.VERIFIED_SUCCESS
    ):
        return EligibilityDecision(
            True,
            "verified_success",
            fast_memory_eligible=True,
            consolidation_eligible=True,
        )

    # Verified failure / blocked → negative Slow samples only (never positive success).
    if experience.reward.label is RewardLabel.NEGATIVE and experience.outcome in {
        ExperienceOutcome.VERIFIED_FAILURE,
        ExperienceOutcome.BLOCKED,
    }:
        if experience.outcome is ExperienceOutcome.VERIFIED_FAILURE and not experience.verified:
            return EligibilityDecision(False, "failure_not_externally_verified")
        return EligibilityDecision(
            True,
            "verified_failure_avoidance",
            fast_memory_eligible=False,
            consolidation_eligible=False,
            failure_memory=True,
            detail={
                "note": "failure retained as negative Slow sample; not promoted as success memory",
                "negative_slow_eligible": True,
            },
        )

    if experience.outcome in {
        ExperienceOutcome.UNVERIFIED_SUCCESS,
        ExperienceOutcome.UNKNOWN,
        ExperienceOutcome.INCOMPLETE,
        ExperienceOutcome.PARTIAL,
        ExperienceOutcome.REJECTED,
        ExperienceOutcome.BLOCKED,
        ExperienceOutcome.CANCELLED,
    }:
        return EligibilityDecision(False, f"outcome_{experience.outcome.value}")

    return EligibilityDecision(False, "not_training_eligible")


class ContinualLearningPipeline:
    """End-to-end Phase 12 learning path with evaluate-before-promote."""

    def __init__(
        self,
        *,
        consolidation: ConsolidationPipeline | None = None,
        fast_session: FastMemorySession | None = None,
    ) -> None:
        self.consolidation = consolidation
        self.fast_session = fast_session

    def process_experience(
        self,
        experience: NeuralExperience,
        *,
        key_vector: Any | None = None,
        value_vector: Any | None = None,
        source_reliability: float = 0.8,
        run_consolidation: bool = False,
        checkpoint_id: str | None = None,
        retention_examples: Sequence[SlowMemoryExample] | None = None,
        eval_examples: Sequence[SlowMemoryExample] | None = None,
        additional_experiences: Sequence[NeuralExperience] | None = None,
        pad_examples: Sequence[SlowMemoryExample] | None = None,
    ) -> ContinualLearningResult:
        life = ExperienceLifecycle(experience.experience_id, source_kind=experience.source)
        eligibility = evaluate_learning_eligibility(experience)

        # Always advance through lifecycle admit for auditable state, then overlay safety.
        record = life.admit_from_neural_experience(experience)
        if not eligibility.eligible:
            if life.state is not ExperienceLifecycleState.REJECTED:
                # Force reject if admit accepted something the safety gate blocks.
                if life.state in {
                    ExperienceLifecycleState.TRAINING_ELIGIBLE,
                    ExperienceLifecycleState.ACCEPTED,
                    ExperienceLifecycleState.FAST_MEMORY,
                    ExperienceLifecycleState.CONSOLIDATION_CANDIDATE,
                }:
                    try:
                        life.transition(
                            ExperienceLifecycleState.REJECTED,
                            reason=eligibility.reason,
                        )
                    except Exception:
                        life = ExperienceLifecycle(experience.experience_id, source_kind=experience.source)
                        life.transition(ExperienceLifecycleState.VERIFICATION)
                        life.transition(ExperienceLifecycleState.REJECTED, reason=eligibility.reason)
                record = life.record
            return ContinualLearningResult(
                experience_id=experience.experience_id,
                lifecycle_state=record.state.value,
                eligibility=eligibility,
                notes=[eligibility.reason],
            )

        # Align lifecycle to TRAINING_ELIGIBLE when safety agrees.
        if record.state is ExperienceLifecycleState.REJECTED:
            return ContinualLearningResult(
                experience_id=experience.experience_id,
                lifecycle_state=record.state.value,
                eligibility=eligibility,
                notes=[record.rejection_reason or "rejected"],
            )

        notes: list[str] = [eligibility.reason]
        fast_payload: dict[str, Any] | None = None
        negative_slow_payload: dict[str, Any] | None = None

        if eligibility.failure_memory:
            from neural.experience import experience_to_negative_slow_example

            neg = experience_to_negative_slow_example(experience)
            if neg is not None:
                negative_slow_payload = {
                    **neg.to_dict(),
                    "polarity": "negative",
                    "success_memory": False,
                }
                notes.append("negative_slow_sample_accepted")
            else:
                notes.append("negative_slow_sample_rejected")

        if (
            eligibility.fast_memory_eligible
            and self.fast_session is not None
            and key_vector is not None
            and value_vector is not None
        ):
            from neural.experience import apply_experience_to_fast_session

            write: FastWriteResult = apply_experience_to_fast_session(
                self.fast_session,
                experience,
                key_vector=key_vector,
                value_vector=value_vector,
                source_reliability=source_reliability,
            )
            fast_payload = write.to_dict()
            if write.accepted:
                life.mark_fast_memory_written()
                notes.append("fast_memory_write_accepted")
            else:
                notes.append(f"fast_memory_write_rejected:{write.decision.reason}")

        consolidation_payload: dict[str, Any] | None = None
        rolled_back = False
        base_unchanged: bool | None = None
        retention_before: float | None = None
        retention_after: float | None = None

        if (
            run_consolidation
            and eligibility.consolidation_eligible
            and self.consolidation is not None
            and checkpoint_id
        ):
            # Mark consolidation path.
            if life.state is ExperienceLifecycleState.TRAINING_ELIGIBLE:
                life.mark_consolidation_candidate()
            elif life.state is ExperienceLifecycleState.FAST_MEMORY:
                life.mark_consolidation_candidate()
            life.mark_slow_candidate()
            life.mark_evaluation()

            batch = list(additional_experiences or [])
            batch.append(experience)
            # Drop any secret/personal experiences from the batch again (defense in depth).
            safe_batch: list[NeuralExperience] = []
            for item in batch:
                decision = evaluate_learning_eligibility(item)
                if decision.consolidation_eligible:
                    safe_batch.append(item)
                else:
                    notes.append(f"batch_excluded:{item.experience_id}:{decision.reason}")

            report: ConsolidationReport = self.consolidation.run(
                checkpoint_id=checkpoint_id,
                experiences=safe_batch,
                examples=list(pad_examples or []),
                eval_examples=list(eval_examples or []),
                retention_examples=list(retention_examples or []),
            )
            consolidation_payload = report.to_dict()
            base_unchanged = report.base_unchanged
            retention_before = report.retention_before
            retention_after = report.retention_after
            if report.promoted:
                life.mark_promoted()
                notes.append("promoted_after_evaluation")
            else:
                life.mark_promotion_rejected(report.reason)
                rolled_back = True
                notes.append(f"promotion_rejected:{report.reason}")

        return ContinualLearningResult(
            experience_id=experience.experience_id,
            lifecycle_state=life.state.value,
            eligibility=eligibility,
            fast_write=fast_payload,
            consolidation=consolidation_payload,
            negative_slow_sample=negative_slow_payload,
            rolled_back=rolled_back,
            base_unchanged=base_unchanged,
            retention_before=retention_before,
            retention_after=retention_after,
            notes=notes,
        )


def raise_if_unsafe_for_slow_memory(experience: NeuralExperience) -> None:
    """Typed hard fail for secret/personal content before Slow Memory training."""
    blob = experience_text_blob(experience)
    if contains_secret_material(blob):
        raise NeuralSecretRejected(
            "secret material cannot enter Slow Neural Memory",
            detail={"experience_id": experience.experience_id},
        )
    if contains_personal_data(blob):
        raise NeuralPersonalDataRejected(
            "personal data should stay in Exact Memory, not Slow Neural Memory",
            detail={"experience_id": experience.experience_id},
        )
