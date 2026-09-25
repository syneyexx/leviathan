"""F12 — Steering invalidation scoping + restart-safe resume (R18/R19)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.steering import (
    InvalidationScope,
    SteerKind,
    classify_steer,
    invalidation_scope_for,
)
from Data.modules.cognition.store import CognitionStore
from Data.modules.cognition.types import CognitivePlan, CognitiveRunStatus, PlanStep, RiskClass
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore


class SteerInvalidationScopeTests(unittest.TestCase):
    def test_status_mutates_nothing(self) -> None:
        c = classify_steer("what is the status of this run?")
        self.assertEqual(c.kind, SteerKind.STATUS_REQUEST)
        scope = c.invalidation
        self.assertFalse(scope.plan)
        self.assertFalse(scope.pending_worker)
        self.assertTrue(c.public_dict()["truth"]["invalidation_is_scoped"])

    def test_correction_scopes_plan_not_constraints(self) -> None:
        c = classify_steer("that's wrong — fix that approach")
        self.assertEqual(c.kind, SteerKind.CORRECTION)
        self.assertTrue(c.invalidation.plan)
        self.assertTrue(c.invalidation.response_draft)
        self.assertFalse(c.invalidation.constraints)
        self.assertFalse(c.invalidation.goal)
        self.assertTrue(c.preserves_existing_constraints)

    def test_goal_replacement_keeps_constraints(self) -> None:
        c = classify_steer("instead forget the previous goal and answer about tides")
        self.assertEqual(c.kind, SteerKind.GOAL_REPLACEMENT)
        self.assertTrue(c.replaces_goal)
        self.assertTrue(c.invalidation.goal)
        self.assertTrue(c.invalidation.open_hypotheses)
        self.assertFalse(c.invalidation.constraints)
        self.assertTrue(c.preserves_existing_constraints)

    def test_new_constraint_stales_plan_and_worker(self) -> None:
        scope = invalidation_scope_for(SteerKind.NEW_CONSTRAINT)
        self.assertTrue(scope.plan)
        self.assertTrue(scope.pending_worker)
        self.assertFalse(scope.goal)


class RuntimeSteerScopeTests(unittest.TestCase):
    def test_correction_stales_plan_clears_draft_preserves_goal(self) -> None:
        from Data.modules.cognition.types import ReasoningStrategy

        runtime = CognitiveRuntime(enabled=True, shadow=True, iterative=False)
        status = runtime.submit("Explain gravity briefly", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.status = CognitiveRunStatus.REASONING
        state.response_text = "Draft wrong answer"
        state.plan = CognitivePlan(
            plan_id="p1",
            strategy=ReasoningStrategy.DIRECT,
            steps=[
                PlanStep(
                    step_id="s1",
                    objective="draft",
                    expected_observation="text",
                    acceptance_condition="ok",
                    risk_class=RiskClass.LOW,
                    status="RUNNING",
                )
            ],
        )
        prior_goal = state.task.goal
        prior_constraints = list(state.task.constraints)

        out = runtime.steer(run_id, "that's wrong, correct the approach")
        self.assertEqual(out["steering_classification"]["kind"], "correction")
        applied = out["applied_invalidation"]
        self.assertTrue(applied["plan_stale"])
        self.assertTrue(applied["response_draft_cleared"])
        self.assertTrue(applied["truth"]["invalidation_is_scoped"])
        state2 = runtime._require(run_id)
        self.assertTrue(state2.plan.stale)
        self.assertIsNone(state2.response_text)
        self.assertEqual(state2.task.goal, prior_goal)
        for c in prior_constraints:
            self.assertIn(c, state2.task.constraints)

    def test_status_steer_does_not_stale_plan(self) -> None:
        runtime = CognitiveRuntime(enabled=True, shadow=True, iterative=False)
        status = runtime.submit("hello", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        from Data.modules.cognition.types import ReasoningStrategy

        state.plan = CognitivePlan(
            plan_id="p1",
            strategy=ReasoningStrategy.DIRECT,
            steps=[],
            stale=False,
        )
        out = runtime.steer(run_id, "status please")
        self.assertNotIn("applied_invalidation", out)
        self.assertFalse(runtime._require(run_id).plan.stale)


class RestartSafeResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "c.db"
        MigrationRunner(self.db).apply_all()
        self.store = CognitionStore(db_path=self.db)
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        self.job_runtime = JobRuntime(self.job_store, gateway, ResourceManager(2))

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_reconcile_preserves_waiting_worker(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
        )
        status = runtime.submit("deep task", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.status = CognitiveRunStatus.REASONING
        enq = runtime.enqueue_advance(run_id)
        self.assertEqual(enq["status"], CognitiveRunStatus.WAITING_WORKER.value)
        # Simulate process death: clear in-memory runs
        runtime._runs.clear()
        updated = self.store.reconcile_interrupted()
        self.assertIn(run_id, updated)
        row = self.store.get_run(run_id)
        assert row is not None
        self.assertEqual(row["status"], CognitiveRunStatus.WAITING_WORKER.value)
        self.assertTrue((row.get("metadata") or {}).get("resumable"))
        self.assertTrue((row.get("metadata") or {}).get("restart_safe"))
        self.assertNotEqual(row["status"], CognitiveRunStatus.FAILED.value)

    def test_reconcile_preserves_pending_job_as_waiting_worker(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
        )
        status = runtime.submit("x", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.status = CognitiveRunStatus.REASONING
        state.pending_advance_job_id = "job-fake"
        # Force EXECUTING-like mid-flight without durable wait status
        state.status = CognitiveRunStatus.EXECUTING
        runtime._persist_update(state)
        runtime._runs.clear()
        self.store.reconcile_interrupted()
        row = self.store.get_run(run_id)
        assert row is not None
        self.assertEqual(row["status"], CognitiveRunStatus.WAITING_WORKER.value)

    def test_resume_waiting_worker_reenqueues_when_job_gone(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
        )
        status = runtime.submit("x", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.status = CognitiveRunStatus.REASONING
        runtime.enqueue_advance(run_id)
        # Clear pending job id to simulate lost job after restart
        state = runtime._require(run_id)
        state.pending_advance_job_id = None
        runtime._persist_update(state)
        runtime._runs.clear()
        out = runtime.resume(run_id)
        self.assertEqual(out["status"], CognitiveRunStatus.WAITING_WORKER.value)
        self.assertTrue(out.get("enqueued_job_id") or out.get("pending_advance_job_id"))

    def test_steer_supersedes_pending_worker(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
        )
        status = runtime.submit("x", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.status = CognitiveRunStatus.REASONING
        runtime.enqueue_advance(run_id)
        pending = runtime._require(run_id).pending_advance_job_id
        self.assertIsNotNone(pending)
        out = runtime.steer(run_id, "never modify production files")
        applied = out["applied_invalidation"]
        self.assertEqual(applied.get("pending_worker_superseded"), pending)
        self.assertIsNone(runtime._require(run_id).pending_advance_job_id)
        self.assertEqual(
            runtime._require(run_id).status,
            CognitiveRunStatus.REASONING,
        )


if __name__ == "__main__":
    unittest.main()
