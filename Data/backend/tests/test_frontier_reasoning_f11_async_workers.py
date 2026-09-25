"""F11 — cognition.advance worker externalization (async deep runs)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Data.backend.migrations import MigrationRunner
from Data.modules.cognition.advance import (
    COGNITION_ADVANCE_CAPABILITY,
    enqueue_cognition_advance,
    should_externalize_advance,
)
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.store import CognitionStore
from Data.modules.cognition.types import CognitiveRunStatus, ReasoningMode
from Data.modules.execution import build_default_catalog
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class CognitionAdvanceContractTests(unittest.TestCase):
    def test_should_externalize_deep_only_when_bound(self) -> None:
        self.assertFalse(
            should_externalize_advance(mode="DEEP", job_runtime_bound=False)
        )
        self.assertTrue(
            should_externalize_advance(mode="DEEP", job_runtime_bound=True)
        )
        self.assertTrue(
            should_externalize_advance(mode="MAXIMUM", job_runtime_bound=True)
        )
        self.assertFalse(
            should_externalize_advance(mode="FAST", job_runtime_bound=True)
        )
        self.assertTrue(
            should_externalize_advance(mode="FAST", force=True, job_runtime_bound=False)
        )

    def test_pool_and_capability_registered(self) -> None:
        self.assertIn("cognition", POOL_CATALOG)
        self.assertEqual(pool_for_capability(COGNITION_ADVANCE_CAPABILITY), "cognition")
        self.assertIn(COGNITION_ADVANCE_CAPABILITY, EXTERNAL_WORKER_CAPABILITIES)
        catalog = build_default_catalog()
        cap = catalog.get(COGNITION_ADVANCE_CAPABILITY)
        self.assertIsNotNone(cap)
        assert cap is not None
        self.assertEqual(cap.metadata.get("worker_kind"), "cognition")
        self.assertTrue(cap.metadata.get("not_a_second_runtime"))


class RuntimeExternalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "cognition.db"
        MigrationRunner(self.db).apply_all()
        self.store = CognitionStore(db_path=self.db)
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        catalog = build_default_catalog()
        from Data.modules.execution import ExecutionGateway

        gateway = ExecutionGateway(catalog=catalog)
        self.job_runtime = JobRuntime(
            self.job_store, gateway, ResourceManager(2)
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_enqueue_advance_sets_waiting_worker(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
            externalize_deep=True,
        )
        status = runtime.submit("hello", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.status = CognitiveRunStatus.REASONING
        out = runtime.enqueue_advance(run_id, max_iterations=1)
        self.assertEqual(out["status"], CognitiveRunStatus.WAITING_WORKER.value)
        self.assertIsNotNone(out.get("pending_advance_job_id") or out.get("enqueued_job_id"))
        job_id = out.get("enqueued_job_id")
        job = self.job_store.get(job_id)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.capability_id, COGNITION_ADVANCE_CAPABILITY)

    def test_deep_run_externalizes_instead_of_inline_loop(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
            externalize_deep=True,
        )
        # Force DEEP via metadata / policy by patching after submit perceive path:
        # submit(run=False) then manually run with deep decision.
        status = runtime.submit(
            "Deep research the latest fusion contradictions carefully",
            run=False,
        )
        run_id = status["run_id"]
        state = runtime._require(run_id)
        # Simulate run() path after plan with forced externalize
        from Data.modules.cognition.meta_controller import MetaController

        decision = MetaController().decide(
            state.task,
            uncertainty=0.9,
            evidence_coverage=0.05,
            user_requested_depth="DEEP",
        )
        state.decision = decision
        self.assertEqual(decision.mode, ReasoningMode.DEEP)
        state.status = CognitiveRunStatus.REASONING
        state.plan = runtime.planner.plan(state.task, decision)
        out = runtime._externalize_iterative(state)
        self.assertEqual(out["status"], CognitiveRunStatus.WAITING_WORKER.value)
        self.assertTrue(out["truth"].get("cognition_advance_externalizable"))

    def test_advance_external_bounded_batch(self) -> None:
        runtime = CognitiveRuntime(
            enabled=True,
            shadow=True,  # shadow finalize quickly without model
            iterative=True,
            store=self.store,
            job_runtime=self.job_runtime,
            externalize_deep=False,
        )
        # For advance_external test use non-shadow after create:
        status = runtime.submit("Explain gravity", run=False)
        run_id = status["run_id"]
        live = runtime._require(run_id)
        live.shadow = False
        live.status = CognitiveRunStatus.WAITING_WORKER
        live.decision = runtime._meta_decide(live)
        live.plan = runtime.planner.plan(live.task, live.decision)
        # Without model_caller, MODEL_CALL/RESPOND may fail soft; still advances.
        result = runtime.advance_external(run_id, max_iterations=1, requeue=False)
        self.assertEqual(result["run_id"], run_id)
        self.assertTrue(result["truth"]["cognition_advance_is_externalized"])
        self.assertTrue(result["truth"]["not_a_second_runtime"])
        self.assertGreaterEqual(result["iterations_advanced"], 1)

    def test_enqueue_idempotent(self) -> None:
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
        state.usage.iterations = 3
        a = enqueue_cognition_advance(
            self.job_runtime, run_id=run_id, cursor_iteration=3
        )
        b = enqueue_cognition_advance(
            self.job_runtime, run_id=run_id, cursor_iteration=3
        )
        self.assertEqual(a.job_id, b.job_id)


class EntrypointImportTests(unittest.TestCase):
    def test_cognition_entrypoint_importable(self) -> None:
        from Data.modules.workers.entrypoints import cognition as ep

        self.assertTrue(callable(ep._handler))
        self.assertTrue(callable(ep.main))


if __name__ == "__main__":
    unittest.main()
