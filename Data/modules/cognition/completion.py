"""Completion authority — model text does not decide completion.

Criterion evaluation is evidence/observation based. Lexical presence of
words like "passed" / "completed" in model prose is NEVER sufficient.

W03: prefer typed ``TaskModel.acceptance_criteria`` with criterion IDs and
verifier kinds. Legacy string ``success_criteria`` remain as compatibility
input via coerce_acceptance_criteria; unsupported legacy semantics stay
unverified and never auto-pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from Data.modules.verification.types import CriterionVerificationStatus, VerifierKind

from .task_model import AcceptanceCriterion, TaskModel, coerce_acceptance_criteria
from .types import CognitiveObservation, CognitiveObservationKind, CognitiveRunStatus, RiskClass

# Trusted capability IDs that may satisfy a tests_passed criterion.
_TRUSTED_TEST_CAPABILITIES = frozenset(
    {
        "coding.run_tests",
        "coding.test",
        "pytest.run",
        "tests.run",
    }
)

_NON_TEST_CAPABILITIES = frozenset(
    {
        "shell.exec",
        "shell.run",
        "subprocess.run",
        "filesystem.list",
        "filesystem.ls",
        "file.list",
        "workspace.list",
        "os.listdir",
    }
)


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    met: bool
    detail: str | None = None
    criterion_id: str | None = None
    verification_status: str = CriterionVerificationStatus.UNVERIFIED.value
    verifier_kind: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "criterion_id": self.criterion_id,
            "met": self.met,
            "detail": self.detail,
            "verification_status": self.verification_status,
            "verifier_kind": self.verifier_kind,
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
                "unrelated_receipts_do_not_pass_tests": True,
                "typed_criteria_preferred": True,
            },
        }


def _obs_has_kind(observations: list[CognitiveObservation], kind: CognitiveObservationKind) -> bool:
    return any(o.kind == kind for o in observations)


def _obs_with_claim_support(observations: list[CognitiveObservation]) -> CriterionVerificationStatus:
    """Source ID presence alone is insufficient — need claim-support provenance."""
    for o in observations:
        payload = o.payload or {}
        if payload.get("model_authored_evidence") is True:
            continue
        if payload.get("claim_supported") is True and (
            payload.get("span") or payload.get("quote") or payload.get("evidence_id")
        ):
            return CriterionVerificationStatus.SUPPORTED
        if payload.get("claim_supported") is False or payload.get("contradicted") is True:
            return CriterionVerificationStatus.CONTRADICTED
        if o.evidence_refs and payload.get("independent_claim_support"):
            return CriterionVerificationStatus.SUPPORTED
    if any(bool(o.evidence_refs) for o in observations):
        return CriterionVerificationStatus.INSUFFICIENT_EVIDENCE
    return CriterionVerificationStatus.INSUFFICIENT_EVIDENCE


def _trusted_test_receipt(
    observations: list[CognitiveObservation],
    *,
    expected_attempt_id: str | None = None,
    expected_artifact_revision: str | None = None,
) -> tuple[CriterionVerificationStatus, str]:
    """exit_code=0 only counts when a trusted test receipt identifies the suite.

    Required on a supporting receipt:
    - trusted capability or kind=test_receipt (not shell/ls)
    - test command/suite identity
    - actual execution marker
    - workspace/artifact revision
    - current attempt id
    - non-model provenance

    A successful directory listing / unrelated shell command cannot satisfy tests.
    """
    found_untrusted = False
    found_incomplete = False
    found_stale = False
    found_failed = False

    for o in observations:
        if o.kind == CognitiveObservationKind.MODEL_RESULT:
            continue
        payload = dict(o.payload or {})
        # Model-authored evidence fields are never authoritative.
        if payload.get("model_authored_evidence") is True or payload.get("model_authored") is True:
            found_untrusted = True
            continue
        authored = str(payload.get("authored_by") or "").lower()
        prov = payload.get("provenance")
        if authored in {"model", "model_authored", "assistant", "llm"}:
            found_untrusted = True
            continue
        if isinstance(prov, str) and prov.lower() in {"model", "model_authored", "assistant", "llm"}:
            found_untrusted = True
            continue

        capability = str(payload.get("capability_id") or "").strip()
        kind = str(payload.get("kind") or "").strip().lower()
        is_trusted = kind == "test_receipt" or capability in _TRUSTED_TEST_CAPABILITIES

        if capability in _NON_TEST_CAPABILITIES or (capability and not is_trusted):
            if "exit_code" in payload or "tests_passed" in payload or "passed" in payload:
                found_untrusted = True
            continue
        if not is_trusted:
            continue

        suite = (
            payload.get("test_suite")
            or payload.get("test_command")
            or payload.get("command")
            or payload.get("selector")
            or payload.get("test_selector")
        )
        if not suite or not str(suite).strip():
            found_incomplete = True
            continue

        executed = payload.get("executed")
        if executed is None:
            executed = payload.get("execution") == "completed"
        if executed is not True and "exit_code" not in payload and "tests_passed" not in payload:
            found_incomplete = True
            continue

        attempt_id = payload.get("attempt_id") or payload.get("run_attempt_id")
        if not attempt_id:
            found_incomplete = True
            continue
        if expected_attempt_id and str(attempt_id) != str(expected_attempt_id):
            found_incomplete = True
            continue

        revision = (
            payload.get("artifact_revision")
            or payload.get("workspace_revision")
            or payload.get("revision")
            or payload.get("content_hash")
        )
        if not revision:
            found_incomplete = True
            continue
        if expected_artifact_revision and str(revision) != str(expected_artifact_revision):
            found_stale = True
            continue
        if payload.get("stale") is True or payload.get("fresh") is False:
            found_stale = True
            continue

        passed: bool | None = None
        if "tests_passed" in payload:
            passed = bool(payload.get("tests_passed"))
        elif "passed" in payload:
            passed = bool(payload.get("passed"))
        elif "exit_code" in payload:
            try:
                passed = int(payload["exit_code"]) == 0
            except (TypeError, ValueError):
                found_failed = True
                continue
        elif o.success is not None and capability in _TRUSTED_TEST_CAPABILITIES:
            found_incomplete = True
            continue

        if passed is True:
            return CriterionVerificationStatus.SUPPORTED, f"trusted test receipt passed ({suite})"
        if passed is False:
            found_failed = True
            continue
        found_incomplete = True

    if found_failed:
        return CriterionVerificationStatus.FAILED_EXECUTION, "trusted test receipt failed"
    if found_stale:
        return (
            CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
            "stale or revision-mismatched test receipt",
        )
    if found_untrusted:
        return (
            CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
            "unrelated shell/exit_code receipt cannot satisfy tests_passed",
        )
    if found_incomplete:
        return (
            CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
            "test receipt incomplete (suite/command, execution, revision, attempt)",
        )
    return CriterionVerificationStatus.INSUFFICIENT_EVIDENCE, "no trusted test receipt"



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
        # Only SUPPORTED counts as met; UNVERIFIED/INSUFFICIENT never auto-pass.
        met = sum(1 for c in criteria if c.met)
        total = len(criteria) or 1
        verification_required = bool(task.required_evidence) or task.risk_class in {
            RiskClass.HIGH,
            RiskClass.CRITICAL,
        } or any(
            c.verification_status
            in {
                CriterionVerificationStatus.INSUFFICIENT_EVIDENCE.value,
                CriterionVerificationStatus.FAILED_EXECUTION.value,
                CriterionVerificationStatus.CONTRADICTED.value,
            }
            for c in criteria
            if c.verifier_kind
            in {VerifierKind.TEST_RECEIPT.value, VerifierKind.EVIDENCE_STORE.value, VerifierKind.ARTIFACT.value}
        )

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
        # Low-risk conversation may finish without pretending to be verified.
        if response_text and task.task_type == "simple_chat" and task.risk_class == RiskClass.LOW:
            return CompletionDecision(
                status=CognitiveRunStatus.COMPLETED_UNVERIFIED,
                criteria=criteria,
                reason="simple chat reply produced (unverified)",
                verification_required=False,
                verification_passed=None,
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
        typed = list(task.acceptance_criteria or [])
        if not typed and task.success_criteria:
            typed = coerce_acceptance_criteria(None, legacy_strings=task.success_criteria)
        results: list[CriterionResult] = []
        meta = getattr(task, "metadata", None) or {}
        attempt_id = None
        artifact_rev = None
        if isinstance(meta, dict):
            attempt_id = meta.get("attempt_id") or meta.get("current_attempt")
            artifact_rev = meta.get("workspace_revision") or meta.get("artifact_revision")
        # Observations may carry the current attempt/revision when task metadata omits them;
        # matching is still enforced only against expected values from task scope.
        for criterion in typed:
            status, detail, met = self._evaluate_typed(
                criterion,
                observations=observations,
                response_text=response_text,
                task=task,
                expected_attempt_id=str(attempt_id) if attempt_id else None,
                expected_artifact_revision=str(artifact_rev) if artifact_rev else None,
            )
            results.append(
                CriterionResult(
                    criterion=criterion.description or criterion.predicate,
                    criterion_id=criterion.criterion_id,
                    met=met,
                    detail=detail,
                    verification_status=status.value,
                    verifier_kind=criterion.verifier_kind.value,
                )
            )
        return results

    def _evaluate_typed(
        self,
        criterion: AcceptanceCriterion,
        *,
        observations: list[CognitiveObservation],
        response_text: str | None,
        task: TaskModel,
        expected_attempt_id: str | None,
        expected_artifact_revision: str | None,
    ) -> tuple[CriterionVerificationStatus, str, bool]:
        kind = criterion.verifier_kind
        if kind == VerifierKind.LEGACY_UNSUPPORTED or kind == VerifierKind.UNAVAILABLE:
            return (
                CriterionVerificationStatus.UNVERIFIED
                if kind == VerifierKind.LEGACY_UNSUPPORTED
                else CriterionVerificationStatus.UNAVAILABLE_VERIFIER,
                "unsupported/unavailable verifier — not auto-passed",
                False,
            )

        if kind == VerifierKind.TEST_RECEIPT or criterion.predicate == "tests_passed":
            status, detail = _trusted_test_receipt(
                observations,
                expected_attempt_id=expected_attempt_id,
                expected_artifact_revision=expected_artifact_revision,
            )
            return status, detail, status == CriterionVerificationStatus.SUPPORTED

        if kind == VerifierKind.EVIDENCE_STORE or criterion.predicate in {
            "claim_supported",
            "knowledge_grounded",
        }:
            status = _obs_with_claim_support(observations)
            detail = {
                CriterionVerificationStatus.SUPPORTED: "claim support with provenance",
                CriterionVerificationStatus.CONTRADICTED: "claim contradicted by evidence",
                CriterionVerificationStatus.INSUFFICIENT_EVIDENCE: "evidence refs alone do not support claim",
            }.get(status, status.value)
            return status, detail, status == CriterionVerificationStatus.SUPPORTED

        if kind == VerifierKind.RESPONSE_PRESENCE:
            text = (response_text or "").strip()
            if criterion.predicate in {"goal_addressed"}:
                failure_markers = (
                    "cannot answer",
                    "could not",
                    "failed",
                    "all tests failed",
                    "no tests passed",
                    "i cannot",
                )
                admits_failure = any(m in text.lower() for m in failure_markers)
                ok = bool(text) and len(text) > 10 and not admits_failure
                status = (
                    CriterionVerificationStatus.SUPPORTED
                    if ok
                    else CriterionVerificationStatus.INSUFFICIENT_EVIDENCE
                )
                detail = (
                    "substantive reply"
                    if ok
                    else ("reply admits failure" if admits_failure else "reply missing/too short")
                )
                return status, detail, ok
            ok = bool(text)
            status = (
                CriterionVerificationStatus.SUPPORTED
                if ok
                else CriterionVerificationStatus.INSUFFICIENT_EVIDENCE
            )
            return status, ("response present" if ok else "no response"), ok

        if kind == VerifierKind.ARTIFACT or criterion.predicate == "artifact_present":
            expected = criterion.expected_artifact
            for o in observations:
                payload = o.payload or {}
                if payload.get("model_authored_evidence") is True:
                    continue
                art = payload.get("artifact_id") or payload.get("artifact_ref")
                if not art:
                    continue
                if expected and str(art) != str(expected):
                    continue
                if payload.get("fake_artifact") is True:
                    continue
                return CriterionVerificationStatus.SUPPORTED, "artifact receipt present", True
            return (
                CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
                "no matching artifact receipt",
                False,
            )

        if kind == VerifierKind.HONESTY:
            return CriterionVerificationStatus.SUPPORTED, "honesty constraint tracked", True

        if kind == VerifierKind.OBSERVATION:
            if criterion.predicate == "conflict_surfaced":
                has_conflict = any(
                    "contradict" in (o.summary or "").lower()
                    or (o.payload or {}).get("conflicts")
                    or (
                        o.kind == CognitiveObservationKind.SYSTEM_STATE
                        and (o.payload or {}).get("conflict_resolved") is True
                    )
                    for o in observations
                )
                if any("conflict" in (o.summary or "").lower() for o in observations):
                    ok = has_conflict or any(
                        (o.payload or {}).get("conflict_resolved") is True for o in observations
                    )
                    return (
                        CriterionVerificationStatus.SUPPORTED
                        if ok
                        else CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
                        "conflict observation handled" if ok else "conflict unresolved",
                        ok,
                    )
                return (
                    CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
                    "no conflict observations to satisfy criterion",
                    False,
                )
            if criterion.predicate == "approval_respected":
                ok = _obs_has_kind(observations, CognitiveObservationKind.APPROVAL_RESULT) or (
                    not task.side_effect_expectations
                )
                return (
                    CriterionVerificationStatus.SUPPORTED
                    if ok
                    else CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
                    "approval path respected" if ok else "approval missing",
                    ok,
                )
            if criterion.predicate == "observations_recorded":
                ok = bool(observations)
                return (
                    CriterionVerificationStatus.SUPPORTED
                    if ok
                    else CriterionVerificationStatus.INSUFFICIENT_EVIDENCE,
                    "observations recorded" if ok else "no observations",
                    ok,
                )
            # Explicit satisfaction observation by criterion_id only.
            ok = any(
                (o.payload or {}).get("criterion_id") == criterion.criterion_id
                or (o.payload or {}).get("satisfies_criterion") == criterion.criterion_id
                for o in observations
            )
            return (
                CriterionVerificationStatus.SUPPORTED
                if ok
                else CriterionVerificationStatus.UNVERIFIED,
                "explicit criterion satisfaction observation"
                if ok
                else "no explicit satisfaction observation (prose ignored)",
                ok,
            )

        return CriterionVerificationStatus.UNAVAILABLE_VERIFIER, f"unknown verifier {kind}", False


# Back-compat alias used by older tests.
def _test_receipt_passed(observations: list[CognitiveObservation]) -> bool | None:
    status, _ = _trusted_test_receipt(observations)
    if status == CriterionVerificationStatus.SUPPORTED:
        return True
    if status == CriterionVerificationStatus.FAILED_EXECUTION:
        return False
    return None


def evaluate_test_receipt(
    observations: list[CognitiveObservation],
    *,
    expected_attempt_id: str | None = None,
    expected_artifact_revision: str | None = None,
) -> dict[str, Any]:
    """Public helper for trusted test-receipt evaluation (A04 / W03)."""
    status, detail = _trusted_test_receipt(
        observations,
        expected_attempt_id=expected_attempt_id,
        expected_artifact_revision=expected_artifact_revision,
    )
    return {
        "status": status.value,
        "detail": detail,
        "passed": status == CriterionVerificationStatus.SUPPORTED,
        "truth": {
            "unrelated_shell_exit_zero_is_not_tests_passed": True,
            "model_authored_evidence_ignored": True,
        },
    }