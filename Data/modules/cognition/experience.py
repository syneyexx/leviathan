"""VerifiedExperience + admission policy + procedural memory hints."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .task_model import TaskModel
from .types import CognitiveRunStatus, ReasoningStrategy


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class VerifiedExperience:
    experience_id: str
    task_type: str
    domain: str
    task_summary: str
    strategy: str
    outcome: str
    verification_status: str
    relevant_context_refs: list[str] = field(default_factory=list)
    action_sequence_summary: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    reward: float | None = None
    failures: list[str] = field(default_factory=list)
    recovery_pattern: str | None = None
    resource_usage: dict[str, Any] = field(default_factory=dict)
    model_roles: list[str] = field(default_factory=list)
    tool_usage: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    admitted: bool = False
    admission_reason: str | None = None
    privacy_class: str = "standard"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "task_type": self.task_type,
            "domain": self.domain,
            "task_summary": self.task_summary,
            "strategy": self.strategy,
            "outcome": self.outcome,
            "verification_status": self.verification_status,
            "relevant_context_refs": list(self.relevant_context_refs),
            "action_sequence_summary": list(self.action_sequence_summary),
            "evidence_refs": list(self.evidence_refs),
            "reward": self.reward,
            "failures": list(self.failures),
            "recovery_pattern": self.recovery_pattern,
            "resource_usage": dict(self.resource_usage),
            "model_roles": list(self.model_roles),
            "tool_usage": list(self.tool_usage),
            "created_at": self.created_at,
            "admitted": self.admitted,
            "admission_reason": self.admission_reason,
            "privacy_class": self.privacy_class,
            "metadata": self.metadata,
            "truth": {
                "unverified_is_not_training_truth": True,
                "model_output_is_not_automatic_experience": True,
            },
        }


@dataclass
class ProceduralMemoryHint:
    domain: str
    pattern: str
    strategy: str
    historical_success: str
    verification: str
    advisory_only: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "pattern": self.pattern,
            "strategy": self.strategy,
            "historical_success": self.historical_success,
            "verification": self.verification,
            "advisory_only": self.advisory_only,
            "truth": {"procedural_memory_is_advisory": True},
        }


class ExperienceAdmissionPolicy:
    """Only sufficiently verified experiences may become strong learning input."""

    FORBIDDEN_PRIVACY = {"secret", "credentials", "sensitive"}

    def evaluate(self, experience: VerifiedExperience) -> tuple[bool, str]:
        if experience.privacy_class.lower() in self.FORBIDDEN_PRIVACY:
            return False, "privacy_class_ineligible"
        if experience.verification_status not in {"PASSED", "COMPLETED_VERIFIED", "verified"}:
            return False, "verification_insufficient"
        if experience.outcome not in {
            CognitiveRunStatus.COMPLETED_VERIFIED.value,
            "success",
            "COMPLETED_VERIFIED",
        }:
            return False, "outcome_not_verified_success"
        if experience.reward is not None and experience.reward < 0:
            return False, "negative_reward"
        # Hallucination-without-complaint is NOT positive experience.
        if experience.metadata.get("user_unverified_acceptance"):
            return False, "user_acceptance_without_verification"
        return True, "admitted_verified_experience"


class ExperienceStore:
    """In-memory + optional SQLite-backed experience registry."""

    def __init__(self, store: Any | None = None) -> None:
        self._items: dict[str, VerifiedExperience] = {}
        self._procedural: list[ProceduralMemoryHint] = []
        self._active_learning: list[dict[str, Any]] = []
        self._db_store = store
        self.policy = ExperienceAdmissionPolicy()

    def build_from_run(
        self,
        *,
        task: TaskModel,
        status: CognitiveRunStatus,
        strategy: ReasoningStrategy | str,
        action_summaries: list[str],
        evidence_refs: list[str] | None = None,
        verification_status: str = "UNMEASURED",
        resource_usage: dict[str, Any] | None = None,
        failures: list[str] | None = None,
        model_roles: list[str] | None = None,
        tool_usage: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VerifiedExperience:
        reward = None
        if status == CognitiveRunStatus.COMPLETED_VERIFIED:
            reward = 1.0
        elif status == CognitiveRunStatus.PARTIAL:
            reward = 0.4
        elif status in {CognitiveRunStatus.FAILED, CognitiveRunStatus.CANCELLED}:
            reward = 0.0
        return VerifiedExperience(
            experience_id=str(uuid.uuid4()),
            task_type=task.task_type,
            domain=task.domain,
            task_summary=task.goal[:500],
            strategy=strategy.value if isinstance(strategy, ReasoningStrategy) else str(strategy),
            outcome=status.value,
            verification_status=verification_status,
            action_sequence_summary=list(action_summaries),
            evidence_refs=list(evidence_refs or []),
            reward=reward,
            failures=list(failures or []),
            resource_usage=dict(resource_usage or {}),
            model_roles=list(model_roles or []),
            tool_usage=list(tool_usage or []),
            privacy_class=task.privacy_class,
            metadata=dict(metadata or {}),
        )

    def admit(self, experience: VerifiedExperience) -> VerifiedExperience:
        ok, reason = self.policy.evaluate(experience)
        experience.admitted = ok
        experience.admission_reason = reason
        self._items[experience.experience_id] = experience
        if self._db_store is not None and hasattr(self._db_store, "save_experience"):
            self._db_store.save_experience(experience)
        if ok:
            self._procedural.append(
                ProceduralMemoryHint(
                    domain=experience.domain,
                    pattern=experience.task_type,
                    strategy=experience.strategy,
                    historical_success="1/1",
                    verification=experience.verification_status,
                )
            )
        return experience

    def list_admitted(self) -> list[VerifiedExperience]:
        return [e for e in self._items.values() if e.admitted]

    def procedural_hints(self, *, domain: str | None = None) -> list[ProceduralMemoryHint]:
        if domain is None:
            return list(self._procedural)
        return [p for p in self._procedural if p.domain == domain]

    def record_active_learning_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Queue a structured active-learning candidate — never auto-trains."""
        payload = {
            **dict(candidate),
            "candidate_id": str(candidate.get("candidate_id") or uuid.uuid4()),
            "requires_human_or_policy_approval": True,
            "auto_promote_forbidden": True,
            "created_at": candidate.get("created_at") or _now(),
        }
        self._active_learning.append(payload)
        return payload

    def training_candidates(self) -> list[dict[str, Any]]:
        """Controlled bridge payload — never auto-promotes models."""
        admitted = [
            {
                "experience_id": e.experience_id,
                "domain": e.domain,
                "strategy": e.strategy,
                "verification_status": e.verification_status,
                "requires_human_or_policy_approval": True,
                "auto_promote_forbidden": True,
                "source": "verified_experience",
            }
            for e in self.list_admitted()
        ]
        active = [
            {
                **c,
                "requires_human_or_policy_approval": True,
                "auto_promote_forbidden": True,
                "source": c.get("source") or "active_learning",
            }
            for c in self._active_learning
        ]
        return admitted + active
