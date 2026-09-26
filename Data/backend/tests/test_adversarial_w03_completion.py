"""Adversarial completion / verification cases (W03 A04)."""

from __future__ import annotations

import unittest

from Data.modules.cognition.completion import CompletionEngine
from Data.modules.cognition.task_model import AcceptanceCriterion, TaskModel
from Data.modules.cognition.types import CognitiveObservation, CognitiveObservationKind, RiskClass
from Data.modules.verification.types import VerifierKind


class CompletionTypedCriteriaTests(unittest.TestCase):
    def _task(self, *criteria: AcceptanceCriterion) -> TaskModel:
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
                payload={
                    "kind": "test_receipt",
                    "capability_id": "coding.run_tests",
                    "test_suite": "pytest Data/backend/tests",
                    "executed": True,
                    "exit_code": 0,
                    "tests_passed": True,
                    "attempt_id": "a1",
                    "workspace_revision": "rev1",
                },
            )
        ]
        decision = engine.evaluate(
            task, observations=obs, response_text="fixed", verification_passed=True
        )
        self.assertTrue(decision.criteria[0].met)

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


if __name__ == "__main__":
    unittest.main()
