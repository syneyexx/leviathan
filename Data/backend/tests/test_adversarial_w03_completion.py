"""Adversarial completion / verification cases (W03 A04+)."""

from __future__ import annotations

import unittest

from Data.modules.cognition.completion import CompletionEngine, evaluate_test_receipt
from Data.modules.cognition.task_model import AcceptanceCriterion, TaskModel, TaskModelBuilder
from Data.modules.cognition.types import (
    CognitiveObservation,
    CognitiveObservationKind,
    CognitiveRunStatus,
    RiskClass,
)
from Data.modules.verification.types import CriterionVerificationStatus, VerifierKind


def _trusted_pass_payload(**overrides: object) -> dict:
    base = {
        "kind": "test_receipt",
        "capability_id": "coding.run_tests",
        "test_suite": "pytest Data/backend/tests",
        "executed": True,
        "exit_code": 0,
        "tests_passed": True,
        "attempt_id": "a1",
        "workspace_revision": "rev1",
    }
    base.update(overrides)
    return base


class CompletionTypedCriteriaTests(unittest.TestCase):
    def _task(self, *criteria: AcceptanceCriterion, **kwargs) -> TaskModel:
        return TaskModel(
            task_id="t1",
            run_id="r1",
            raw_request="fix bug and run tests",
            goal="fix",
            domain="coding",
            task_type="coding",
            risk_class=RiskClass.HIGH,
            acceptance_criteria=list(criteria),
            success_criteria=[c.description for c in criteria],
            required_evidence=["trusted_test_receipt"],
            metadata=dict(kwargs.get("metadata") or {}),
        )

    def test_a04_unrelated_shell_exit_zero_does_not_pass_tests(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:tests",
                predicate="tests_passed",
                description="tests passed",
                verifier_kind=VerifierKind.TEST_RECEIPT,
                required_evidence=("trusted_test_receipt",),
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="ls ok",
                success=True,
                payload={
                    "capability_id": "shell.exec",
                    "command": "ls",
                    "exit_code": 0,
                },
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="done")
        self.assertFalse(decision.criteria[0].met)
        self.assertIn("unrelated", (decision.criteria[0].detail or "").lower())
        helper = evaluate_test_receipt(obs)
        self.assertFalse(helper["passed"])

    def test_directory_listing_cannot_satisfy_tests(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:tests",
                predicate="tests_passed",
                description="tests passed",
                verifier_kind=VerifierKind.TEST_RECEIPT,
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="listed workspace",
                success=True,
                payload={
                    "capability_id": "filesystem.list",
                    "exit_code": 0,
                    "entries": ["a.py", "b.py"],
                },
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="tests passed")
        self.assertFalse(decision.criteria[0].met)

    def test_trusted_test_receipt_with_suite_can_pass(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:tests",
                predicate="tests_passed",
                description="tests passed",
                verifier_kind=VerifierKind.TEST_RECEIPT,
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="pytest",
                success=True,
                payload=_trusted_pass_payload(),
            )
        ]
        decision = engine.evaluate(
            task, observations=obs, response_text="fixed", verification_passed=True
        )
        self.assertTrue(decision.criteria[0].met)
        self.assertEqual(
            decision.criteria[0].verification_status,
            CriterionVerificationStatus.SUPPORTED.value,
        )

    def test_stale_test_receipt_does_not_pass(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:tests",
                predicate="tests_passed",
                description="tests passed",
                verifier_kind=VerifierKind.TEST_RECEIPT,
            ),
            metadata={"workspace_revision": "rev-current", "attempt_id": "a1"},
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="pytest stale",
                success=True,
                payload=_trusted_pass_payload(workspace_revision="rev-old", stale=True),
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="fixed")
        self.assertFalse(decision.criteria[0].met)
        self.assertIn("stale", (decision.criteria[0].detail or "").lower())

    def test_fake_artifact_id_does_not_pass(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:art",
                predicate="artifact_present",
                description="artifact present",
                expected_artifact="art-real",
                verifier_kind=VerifierKind.ARTIFACT,
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="fake art",
                success=True,
                payload={"artifact_id": "art-fake", "fake_artifact": True},
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="shipped")
        self.assertFalse(decision.criteria[0].met)

    def test_model_authored_evidence_fields_rejected(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:tests",
                predicate="tests_passed",
                description="tests passed",
                verifier_kind=VerifierKind.TEST_RECEIPT,
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="model claimed",
                success=True,
                payload=_trusted_pass_payload(model_authored_evidence=True),
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="green")
        self.assertFalse(decision.criteria[0].met)

    def test_incomplete_receipt_missing_attempt_or_revision(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:tests",
                predicate="tests_passed",
                description="tests passed",
                verifier_kind=VerifierKind.TEST_RECEIPT,
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.TOOL_RESULT,
                summary="pytest incomplete",
                success=True,
                payload={
                    "kind": "test_receipt",
                    "capability_id": "coding.run_tests",
                    "test_suite": "pytest",
                    "executed": True,
                    "exit_code": 0,
                    "tests_passed": True,
                    # missing attempt_id + workspace_revision
                },
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="green")
        self.assertFalse(decision.criteria[0].met)
        self.assertEqual(
            decision.criteria[0].verification_status,
            CriterionVerificationStatus.INSUFFICIENT_EVIDENCE.value,
        )

    def test_source_ref_alone_does_not_support_claim(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:claim",
                predicate="claim_supported",
                description="claim supported",
                verifier_kind=VerifierKind.EVIDENCE_STORE,
            )
        )
        obs = [
            CognitiveObservation(
                observation_id="o1",
                kind=CognitiveObservationKind.RETRIEVAL_RESULT,
                summary="hit",
                evidence_refs=("src:1",),
                payload={},
            )
        ]
        decision = engine.evaluate(task, observations=obs, response_text="because source")
        self.assertFalse(decision.criteria[0].met)

    def test_unknown_predicate_does_not_pass(self) -> None:
        engine = CompletionEngine()
        task = self._task(
            AcceptanceCriterion(
                criterion_id="crit:weird",
                predicate="unknown_magic",
                description="do magic",
                verifier_kind=VerifierKind.LEGACY_UNSUPPORTED,
            )
        )
        decision = engine.evaluate(task, observations=[], response_text="magic done")
        self.assertFalse(decision.criteria[0].met)
        self.assertEqual(decision.criteria[0].verification_status, "unverified")

    def test_legacy_unsupported_string_is_unverified(self) -> None:
        engine = CompletionEngine()
        task = TaskModel(
            task_id="t2",
            run_id="r2",
            raw_request="do something vague",
            goal="x",
            domain="general",
            task_type="general",
            success_criteria=["be maximally cosmic"],
            acceptance_criteria=[],
        )
        decision = engine.evaluate(task, observations=[], response_text="sure")
        self.assertEqual(len(decision.criteria), 1)
        self.assertFalse(decision.criteria[0].met)
        self.assertEqual(decision.criteria[0].verification_status, "unverified")

    def test_low_risk_chat_finishes_unverified(self) -> None:
        task = TaskModelBuilder().build("hoi")
        decision = CompletionEngine().evaluate(
            task,
            observations=[],
            response_text="Hoi! Waarmee kan ik helpen?",
        )
        self.assertEqual(decision.status, CognitiveRunStatus.COMPLETED_UNVERIFIED)
        self.assertFalse(decision.verification_required)


if __name__ == "__main__":
    unittest.main()
