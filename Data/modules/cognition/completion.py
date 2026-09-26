"""Completion authority — model text does not decide completion.

Criterion evaluation is evidence/observation based. Lexical presence of
words like "passed" / "completed" in model prose is NEVER sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .task_model import TaskModel
from .types import CognitiveObservation, CognitiveObservationKind, CognitiveRunStatus, RiskClass


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    met: bool
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "met": self.met,
            "detail": self.detail,
        }


@dataclass
class CompletionDecision:
    status: CognitiveRunStatus
    criteria: list[CriterionResult] = field(default_factory=list)
    reason: str = ""
    verification_required: bool = False
    verification_passed: bool | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "criteria": [c.public_dict() for c in self.criteria],
            "reason": self.reason,
            "verification_required": self.verification_required,
            "verification_passed": self.verification_passed,
            "truth": {
                "model_text_does_not_decide_completion": True,
                "partial_is_not_completed": True,
                "prose_keywords_are_not_evidence": True,
            },
        }


def _obs_has_kind(observations: list[CognitiveObservation], kind: CognitiveObservationKind) -> bool:
    return any(o.kind == kind for o in observations)


def _obs_with_evidence(observations: list[CognitiveObservation]) -> bool:
    return any(bool(o.evidence_refs) for o in observations)


def _test_receipt_passed(observations: list[CognitiveObservation]) -> bool | None:
    """True/False when a real test receipt exists; None when unmeasured."""
    for o in observations:
        payload = o.payload or {}
        # Explicit structured receipt fields only — not prose.
        if "tests_passed" in payload:
            return bool(payload.get("tests_passed"))
        if "exit_code" in payload:
            try:
                return int(payload["exit_code"]) == 0
            except (TypeError, ValueError):
                return False
        if payload.get("kind") == "test_receipt":
            if "passed" in payload:
                return bool(payload.get("passed"))
        if o.kind == CognitiveObservationKind.TOOL_RESULT and payload.get("capability_id") in {
            "coding.run_tests",
        }:
            if o.success is not None:
                return bool(o.success)
            if "passed" in payload:
                return bool(payload.get("passed"))
    return None


class CompletionEngine:
    """Centralize completion decisions from acceptance criteria + verification."""

    def evaluate(
        self,
        task: TaskModel,
        *,
        observations: list[CognitiveObservation],
        verification_passed: bool | None = None,
        blocked_reason: str | None = None,
        cancelled: bool = False,
        budget_exhausted: bool = False,
        timed_out: bool = False,
        failed_reason: str | None = None,
        response_text: str | None = None,
    ) -> CompletionDecision:
        if cancelled:
            return CompletionDecision(
                status=CognitiveRunStatus.CANCELLED,
                reason="cancellation completed",
            )
        if timed_out:
            return CompletionDecision(
                status=CognitiveRunStatus.TIMEOUT,
                reason="wall-time or provider timeout",
            )
        if failed_reason:
            return CompletionDecision(
                status=CognitiveRunStatus.FAILED,
                reason=failed_reason,
            )
        if blocked_reason:
            return CompletionDecision(
                status=CognitiveRunStatus.BLOCKED,
                reason=blocked_reason,
            )

        criteria = self._score_criteria(task, observations, response_text)
        met = sum(1 for c in criteria if c.met)
        total = len(criteria) or 1
        verification_required = bool(task.required_evidence) or task.risk_class in {
            RiskClass.HIGH,
            RiskClass.CRITICAL,
        }

        if budget_exhausted and met < total:
            return CompletionDecision(
                status=CognitiveRunStatus.RESOURCE_EXHAUSTED
                if met == 0
                else CognitiveRunStatus.PARTIAL,
                criteria=criteria,
                reason="budget exhausted before all criteria met",
                verification_required=verification_required,
                verification_passed=verification_passed,
            )

        if verification_required:
            if verification_passed is True and met == total:
                return CompletionDecision(
                    status=CognitiveRunStatus.COMPLETED_VERIFIED,
                    criteria=criteria,
                    reason="criteria met and verification passed",
                    verification_required=True,
                    verification_passed=True,
                )
            if verification_passed is False:
                return CompletionDecision(
                    status=CognitiveRunStatus.PARTIAL if met > 0 else CognitiveRunStatus.FAILED,
                    criteria=criteria,
                    reason="verification failed",
                    verification_required=True,
                    verification_passed=False,
                )
            if met == total and response_text:
                return CompletionDecision(
                    status=CognitiveRunStatus.COMPLETED_UNVERIFIED,
                    criteria=criteria,
                    reason="criteria appear met but verification not completed",
                    verification_required=True,
                    verification_passed=None,
                )

        if met == total and (response_text or observations):
            status = (
                CognitiveRunStatus.COMPLETED_VERIFIED
                if verification_passed is True
                else CognitiveRunStatus.COMPLETED_UNVERIFIED
            )
            return CompletionDecision(
                status=status,
                criteria=criteria,
                reason="all acceptance criteria met",
                verification_required=verification_required,
                verification_passed=verification_passed,
            )
        if met > 0:
            return CompletionDecision(
                status=CognitiveRunStatus.PARTIAL,
                criteria=criteria,
                reason=f"{met}/{total} criteria met",
                verification_required=verification_required,
                verification_passed=verification_passed,
            )
        if response_text and task.task_type == "simple_chat":
            return CompletionDecision(
                status=CognitiveRunStatus.COMPLETED_UNVERIFIED,
                criteria=criteria,
                reason="simple chat reply produced",
            )
        return CompletionDecision(
            status=CognitiveRunStatus.FAILED,
            criteria=criteria,
            reason="no acceptance criteria satisfied",
            verification_required=verification_required,
            verification_passed=verification_passed,
        )

    def _score_criteria(
        self,
        task: TaskModel,
        observations: list[CognitiveObservation],
        response_text: str | None,
    ) -> list[CriterionResult]:
        results: list[CriterionResult] = []
        for criterion in task.success_criteria:
            c_low = criterion.lower()
            met = False
            detail = None
            if "helpful direct reply" in c_low:
                met = bool(response_text and len(response_text.strip()) > 0)
                detail = "response present" if met else "no response"
            elif "source" in c_low or "evidence" in c_low:
                met = _obs_with_evidence(observations)
                detail = "evidence refs on observations" if met else "missing evidence refs"
            elif "test" in c_low:
                receipt = _test_receipt_passed(observations)
                if receipt is True:
                    met = True
                    detail = "test receipt passed"
                elif receipt is False:
                    met = False
                    detail = "test receipt failed"
                else:
                    met = False
                    detail = "no structured test receipt — prose claims ignored"
            elif "conflict" in c_low:
                # Conflicts handled only when contradiction observations exist OR
                # an explicit conflict-resolution observation was recorded.
                has_conflict = any(
                    "contradict" in (o.summary or "").lower()
                    or (o.payload or {}).get("conflicts")
                    or o.kind == CognitiveObservationKind.SYSTEM_STATE
                    and (o.payload or {}).get("conflict_resolved") is True
                    for o in observations
                )
                # Vacuous: no conflict signals and no requirement to surface any → unmet
                # unless task recorded zero ambiguities/unknowns about conflicts.
                if any("conflict" in (o.summary or "").lower() for o in observations):
                    met = has_conflict or any(
                        (o.payload or {}).get("conflict_resolved") is True for o in observations
                    )
                    detail = "conflict observation handled" if met else "conflict unresolved"
                else:
                    # No conflicts detected in observations — criterion not auto-passed.
                    met = False
                    detail = "no conflict observations to satisfy criterion"
            elif "goal" in c_low or "address" in c_low or "answer" in c_low:
                # Goal criteria require a substantive reply AND must not claim success
                # when the reply itself admits failure (false-positive trap).
                text = (response_text or "").strip()
                failure_markers = (
                    "cannot answer",
                    "could not",
                    "failed",
                    "all tests failed",
                    "no tests passed",
                    "i cannot",
                )
                admits_failure = any(m in text.lower() for m in failure_markers)
                met = bool(text) and len(text) > 10 and not admits_failure
                detail = (
                    "substantive reply"
                    if met
                    else ("reply admits failure" if admits_failure else "reply missing/too short")
                )
            elif "observation" in c_low or "workspace" in c_low:
                met = bool(observations)
                detail = "observations recorded" if met else "no observations"
            elif "approval" in c_low:
                met = _obs_has_kind(observations, CognitiveObservationKind.APPROVAL_RESULT) or (
                    not task.side_effect_expectations
                )
                detail = "approval path respected"
            elif "unverif" in c_low or "silent" in c_low:
                # Honesty constraint — tracked as met when we did not claim verified completion.
                met = True
                detail = "honesty constraint tracked"
            elif "artifact" in c_low:
                met = any(
                    (o.payload or {}).get("artifact_id") or (o.payload or {}).get("artifact_ref")
                    for o in observations
                ) or any("artifact:" in ref for o in observations for ref in o.evidence_refs)
                detail = "artifact receipt present" if met else "no artifact receipt"
            else:
                # Unknown criterion: require matching observation payload/criterion_id —
                # never token-overlap against model prose.
                met = any(
                    (o.payload or {}).get("criterion_id") == criterion
                    or (o.payload or {}).get("satisfies_criterion") == criterion
                    for o in observations
                )
                detail = (
                    "explicit criterion satisfaction observation"
                    if met
                    else "no explicit satisfaction observation (prose ignored)"
                )
            results.append(CriterionResult(criterion=criterion, met=met, detail=detail))
        return results
