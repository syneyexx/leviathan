"""VerifiedExperience + admission policy + procedural memory hints (v2).

v2 adds aggregate statistics (N, rates, CI by domain/mode/strategy) and richer
active-learning trigger coverage. Unverified output is never training truth;
candidates never auto-promote.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .task_model import TaskModel
from .trajectory_export import (
    PublicCognitiveTrajectory,
    TrajectoryExportBridge,
    build_trajectory_from_run_snapshot,
)
from .types import CognitiveRunStatus, ReasoningStrategy


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def wilson_interval(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion — honest small-N CI."""
    if n <= 0:
        return None
    s = max(0, min(int(successes), int(n)))
    nn = int(n)
    phat = s / nn
    z2 = z * z
    denom = 1.0 + z2 / nn
    centre = phat + z2 / (2.0 * nn)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * nn)) / nn)
    low = max(0.0, (centre - margin) / denom)
    high = min(1.0, (centre + margin) / denom)
    return (low, high)


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
    # v2 axes for aggregates
    mode: str | None = None
    neural_effort: str | None = None
    expected_gain: float | None = None

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
            "mode": self.mode,
            "neural_effort": self.neural_effort,
            "expected_gain": self.expected_gain,
            "metadata": self.metadata,
            "schema_version": "2",
            "truth": {
                "unverified_is_not_training_truth": True,
                "model_output_is_not_automatic_experience": True,
                "experience_v2_aggregates": True,
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
    successes: int = 0
    attempts: int = 0
    mode: str | None = None

    def public_dict(self) -> dict[str, Any]:
        rate = (self.successes / self.attempts) if self.attempts else None
        ci = wilson_interval(self.successes, self.attempts)
        return {
            "domain": self.domain,
            "pattern": self.pattern,
            "strategy": self.strategy,
            "mode": self.mode,
            "historical_success": self.historical_success,
            "verification": self.verification,
            "advisory_only": self.advisory_only,
            "successes": self.successes,
            "attempts": self.attempts,
            "success_rate": rate,
            "wilson_ci_95": list(ci) if ci else None,
            "truth": {
                "procedural_memory_is_advisory": True,
                "n_statistics_required": True,
                "ci_is_not_fabricated_certainty": True,
            },
        }


@dataclass
class BucketStats:
    key: str
    domain: str
    strategy: str
    mode: str
    attempts: int = 0
    successes: int = 0
    verified_successes: int = 0
    failures: int = 0
    partials: int = 0

    def public_dict(self) -> dict[str, Any]:
        rate = (self.successes / self.attempts) if self.attempts else None
        vrate = (self.verified_successes / self.attempts) if self.attempts else None
        ci = wilson_interval(self.successes, self.attempts)
        vci = wilson_interval(self.verified_successes, self.attempts)
        return {
            "key": self.key,
            "domain": self.domain,
            "strategy": self.strategy,
            "mode": self.mode,
            "n": self.attempts,
            "successes": self.successes,
            "verified_successes": self.verified_successes,
            "failures": self.failures,
            "partials": self.partials,
            "success_rate": rate,
            "verified_success_rate": vrate,
            "wilson_ci_95": list(ci) if ci else None,
            "verified_wilson_ci_95": list(vci) if vci else None,
            "truth": {
                "aggregate_n_is_explicit": True,
                "ci_absent_when_n_zero": True,
                "unverified_is_not_counted_as_verified_success": True,
            },
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


# Active-learning trigger ids (never auto-train).
ACTIVE_LEARNING_TRIGGERS = frozenset(
    {
        "verification_failed",
        "high_uncertainty",
        "run_failed",
        "contradiction_dense",
        "low_evidence_research",
        "budget_exhausted",
        "partial_completion",
        "repeated_critic_replan",
        "user_correction",
        "capability_blocked",
        "unresolved_hypotheses",
        "timeout",
    }
)


def evaluate_active_learning_triggers(ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive active-learning candidates from a public run snapshot.

    Returns zero or more candidate payloads — never trains.
    """
    triggers: list[dict[str, Any]] = []
    uncertainty = float(ctx.get("uncertainty") or 0.0)
    verification = ctx.get("verification_passed")
    status = str(ctx.get("status") or "")
    contradiction = float(ctx.get("contradiction_density") or 0.0)
    evidence = float(ctx.get("evidence_coverage") or 0.0)
    requires_research = bool(ctx.get("requires_research"))
    budget_exhausted = bool(ctx.get("budget_exhausted"))
    critic_replans = int(ctx.get("critic_replan_count") or 0)
    user_corrections = int(ctx.get("user_correction_count") or 0)
    capability_blocks = int(ctx.get("capability_block_count") or 0)
    open_hyps = int(ctx.get("open_unresolved_hypothesis_count") or 0)
    timed_out = bool(ctx.get("timed_out")) or status == CognitiveRunStatus.TIMEOUT.value

    def _cand(reason: str, kind: str, **extra: Any) -> dict[str, Any]:
        return {
            "reason": reason,
            "kind": kind,
            "uncertainty": uncertainty,
            "verification_passed": verification,
            "status": status,
            "auto_promote_forbidden": True,
            "requires_human_or_policy_approval": True,
            **extra,
        }

    if verification is False:
        triggers.append(_cand("verification_failed", "failure"))
    if uncertainty >= 0.75:
        triggers.append(_cand("high_uncertainty", "uncertainty"))
    if status == CognitiveRunStatus.FAILED.value:
        triggers.append(_cand("run_failed", "failure"))
    if contradiction >= 0.4:
        triggers.append(
            _cand("contradiction_dense", "consistency", contradiction_density=contradiction)
        )
    if requires_research and evidence < 0.35:
        triggers.append(
            _cand("low_evidence_research", "coverage", evidence_coverage=evidence)
        )
    if budget_exhausted or status == CognitiveRunStatus.RESOURCE_EXHAUSTED.value:
        triggers.append(_cand("budget_exhausted", "resource"))
    if status == CognitiveRunStatus.PARTIAL.value:
        triggers.append(_cand("partial_completion", "partial"))
    if critic_replans >= 2:
        triggers.append(
            _cand("repeated_critic_replan", "critic", critic_replan_count=critic_replans)
        )
    if user_corrections >= 1:
        triggers.append(
            _cand("user_correction", "steering", user_correction_count=user_corrections)
        )
    if capability_blocks >= 1:
        triggers.append(
            _cand("capability_blocked", "capability", capability_block_count=capability_blocks)
        )
    if open_hyps >= 2 and status in {
        CognitiveRunStatus.COMPLETED_UNVERIFIED.value,
        CognitiveRunStatus.PARTIAL.value,
        CognitiveRunStatus.FAILED.value,
    }:
        triggers.append(
            _cand("unresolved_hypotheses", "hypothesis", open_count=open_hyps)
        )
    if timed_out:
        triggers.append(_cand("timeout", "timeout"))
    return triggers


class ExperienceStore:
    """In-memory + optional SQLite-backed experience registry (v2 aggregates)."""

    def __init__(self, store: Any | None = None) -> None:
        self._items: dict[str, VerifiedExperience] = {}
        self._procedural: dict[str, ProceduralMemoryHint] = {}
        self._active_learning: list[dict[str, Any]] = []
        self._buckets: dict[str, BucketStats] = {}
        self._db_store = store
        self.policy = ExperienceAdmissionPolicy()
        self.trajectory_bridge = TrajectoryExportBridge()

    def record_trajectory(
        self,
        trajectory: PublicCognitiveTrajectory,
    ) -> PublicCognitiveTrajectory:
        return self.trajectory_bridge.record(trajectory)

    def record_trajectory_from_run(
        self,
        snapshot: Mapping[str, Any],
        *,
        experience: VerifiedExperience | Mapping[str, Any] | None = None,
    ) -> PublicCognitiveTrajectory:
        traj = build_trajectory_from_run_snapshot(snapshot, experience=experience)
        return self.record_trajectory(traj)

    def export_training_bundle(
        self,
        *,
        include_excluded: bool = False,
        include_active_learning: bool = True,
    ) -> dict[str, Any]:
        """Structured public trajectory bridge — never auto-trains or promotes."""
        return self.trajectory_bridge.export_bundle(
            active_learning=self._active_learning if include_active_learning else [],
            include_excluded=include_excluded,
        )

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
        mode: str | None = None,
        neural_effort: str | None = None,
        expected_gain: float | None = None,
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
            mode=mode,
            neural_effort=neural_effort,
            expected_gain=expected_gain,
        )

    def admit(self, experience: VerifiedExperience) -> VerifiedExperience:
        ok, reason = self.policy.evaluate(experience)
        experience.admitted = ok
        experience.admission_reason = reason
        self._items[experience.experience_id] = experience
        self._update_bucket(experience)
        if self._db_store is not None and hasattr(self._db_store, "save_experience"):
            self._db_store.save_experience(experience)
        if ok:
            self._upsert_procedural(experience)
        return experience

    def _bucket_key(self, domain: str, strategy: str, mode: str | None) -> str:
        return f"{domain}|{strategy}|{mode or 'UNKNOWN'}"

    def _update_bucket(self, experience: VerifiedExperience) -> None:
        key = self._bucket_key(experience.domain, experience.strategy, experience.mode)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = BucketStats(
                key=key,
                domain=experience.domain,
                strategy=experience.strategy,
                mode=experience.mode or "UNKNOWN",
            )
            self._buckets[key] = bucket
        bucket.attempts += 1
        if experience.outcome == CognitiveRunStatus.COMPLETED_VERIFIED.value:
            bucket.successes += 1
            if experience.verification_status in {"PASSED", "COMPLETED_VERIFIED", "verified"}:
                bucket.verified_successes += 1
        elif experience.outcome == CognitiveRunStatus.PARTIAL.value:
            bucket.partials += 1
        elif experience.outcome in {
            CognitiveRunStatus.FAILED.value,
            CognitiveRunStatus.CANCELLED.value,
            CognitiveRunStatus.TIMEOUT.value,
        }:
            bucket.failures += 1
        # COMPLETED_UNVERIFIED counts as attempt but not verified success.

    def _upsert_procedural(self, experience: VerifiedExperience) -> None:
        key = self._bucket_key(experience.domain, experience.strategy, experience.mode)
        hint = self._procedural.get(key)
        if hint is None:
            hint = ProceduralMemoryHint(
                domain=experience.domain,
                pattern=experience.task_type,
                strategy=experience.strategy,
                historical_success="0/0",
                verification=experience.verification_status,
                mode=experience.mode,
            )
            self._procedural[key] = hint
        hint.attempts += 1
        hint.successes += 1  # only admitted verified successes reach here
        hint.historical_success = f"{hint.successes}/{hint.attempts}"
        hint.verification = experience.verification_status

    def list_admitted(self) -> list[VerifiedExperience]:
        return [e for e in self._items.values() if e.admitted]

    def procedural_hints(
        self,
        *,
        domain: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[ProceduralMemoryHint]:
        items = list(self._procedural.values())
        if domain is not None:
            items = [p for p in items if p.domain == domain]
        if query:
            q = query.lower()
            items = [
                p
                for p in items
                if q in p.pattern.lower() or q in p.domain.lower() or q in p.strategy.lower()
            ]
        if limit is not None and limit >= 0:
            items = items[: int(limit)]
        return items

    def aggregates(self, *, domain: str | None = None, min_n: int = 0) -> list[BucketStats]:
        out = list(self._buckets.values())
        if domain is not None:
            out = [b for b in out if b.domain == domain]
        if min_n > 0:
            out = [b for b in out if b.attempts >= min_n]
        return sorted(out, key=lambda b: (-b.attempts, b.key))

    def public_aggregates(self, *, domain: str | None = None, min_n: int = 0) -> dict[str, Any]:
        buckets = self.aggregates(domain=domain, min_n=min_n)
        total_n = sum(b.attempts for b in buckets)
        total_success = sum(b.successes for b in buckets)
        total_verified = sum(b.verified_successes for b in buckets)
        overall_ci = wilson_interval(total_success, total_n)
        return {
            "schema_version": "2",
            "total_n": total_n,
            "total_successes": total_success,
            "total_verified_successes": total_verified,
            "overall_success_rate": (total_success / total_n) if total_n else None,
            "overall_wilson_ci_95": list(overall_ci) if overall_ci else None,
            "buckets": [b.public_dict() for b in buckets],
            "procedural_hints": [h.public_dict() for h in self.procedural_hints(domain=domain)],
            "active_learning_queued": len(self._active_learning),
            "truth": {
                "experience_v2_aggregates": True,
                "n_and_ci_required": True,
                "unverified_is_not_training_truth": True,
                "auto_promote_forbidden": True,
            },
        }

    def record_active_learning_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Queue a structured active-learning candidate — never auto-trains."""
        reason = str(candidate.get("reason") or "unspecified")
        payload = {
            **dict(candidate),
            "candidate_id": str(candidate.get("candidate_id") or uuid.uuid4()),
            "requires_human_or_policy_approval": True,
            "auto_promote_forbidden": True,
            "created_at": candidate.get("created_at") or _now(),
            "trigger_known": reason in ACTIVE_LEARNING_TRIGGERS or reason == "unspecified",
            "truth": {
                "active_learning_never_auto_trains": True,
                "requires_human_or_policy_approval": True,
            },
        }
        self._active_learning.append(payload)
        return payload

    def capture_active_learning_from_context(
        self,
        ctx: Mapping[str, Any],
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        domain: str | None = None,
        goal: str | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate all triggers and enqueue candidates (dedupe by reason per call)."""
        captured: list[dict[str, Any]] = []
        seen: set[str] = set()
        for trig in evaluate_active_learning_triggers(ctx):
            reason = str(trig.get("reason") or "")
            if reason in seen:
                continue
            seen.add(reason)
            payload = self.record_active_learning_candidate(
                {
                    **trig,
                    "run_id": run_id,
                    "task_id": task_id,
                    "domain": domain,
                    "goal": (goal or "")[:300],
                }
            )
            captured.append(payload)
        return captured

    def list_active_learning(self) -> list[dict[str, Any]]:
        return list(self._active_learning)

    def training_candidates(self) -> list[dict[str, Any]]:
        """Controlled bridge payload — never auto-promotes models."""
        admitted = [
            {
                "experience_id": e.experience_id,
                "domain": e.domain,
                "strategy": e.strategy,
                "mode": e.mode,
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
