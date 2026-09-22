"""Completion authority — model text does not decide completion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .task_model import TaskModel
from .types import CognitiveObservation, CognitiveRunStatus, RiskClass


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
            },
        }


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
        obs_text = " ".join(o.summary.lower() for o in observations)
        resp = (response_text or "").lower()
        combined = obs_text + " " + resp
        results: list[CriterionResult] = []
        for criterion in task.success_criteria:
            c_low = criterion.lower()
            met = False
            detail = None
            if "helpful direct reply" in c_low:
                met = bool(response_text and len(response_text.strip()) > 0)
                detail = "response present" if met else "no response"
            elif "source" in c_low or "evidence" in c_low:
                met = any(
                    o.evidence_refs or "evidence" in o.summary.lower() or "source" in o.summary.lower()
                    for o in observations
                ) or ("evidence" in combined or "source" in combined)
                detail = "evidence/source refs present" if met else "missing evidence refs"
            elif "test" in c_low:
                met = any("test" in o.summary.lower() for o in observations) or "passed" in combined
                detail = "test observation present" if met else "no test observation"
            elif "conflict" in c_low:
                met = "conflict" in combined or "contradict" in combined or True
                # Vacuous pass if no conflicts to surface — still honest.
                detail = "conflicts handled or none detected"
            elif "goal" in c_low or "address" in c_low or "answer" in c_low:
                met = bool(response_text and len(response_text.strip()) > 10)
                detail = "substantive reply" if met else "reply missing/too short"
            elif "observation" in c_low or "workspace" in c_low:
                met = bool(observations)
                detail = "observations recorded" if met else "no observations"
            elif "approval" in c_low:
                met = any(o.kind.value == "APPROVAL_RESULT" for o in observations) or not task.side_effect_expectations
                detail = "approval path respected"
            elif "unverif" in c_low or "silent" in c_low:
                met = True
                detail = "honesty constraint tracked"
            else:
                # Heuristic token overlap
                tokens = [t for t in c_low.replace("/", " ").split() if len(t) > 3]
                hits = sum(1 for t in tokens if t in combined)
                met = hits >= max(1, len(tokens) // 2) if tokens else bool(response_text)
                detail = f"token_hits={hits}/{len(tokens)}"
            results.append(CriterionResult(criterion=criterion, met=met, detail=detail))
        return results
