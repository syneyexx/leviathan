"""Durable workflow continuation + market_sim externalize tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.schedules import ScheduleRunner, ScheduleStore, ScheduleTargetKind
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef
from Data.modules.workflows.store import WorkflowStore
from Data.modules.workflows.types import WorkflowState
from Data.modules.workers.pools import pool_for_capability


class WorkflowAdvanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "wf.db"
        self.artifacts = ArtifactStore(self.db, root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(self.db, data_root=root / "corpus", chunk_max_chars=200)
        self.knowledge.initialize()
        (root / "corpus").mkdir(parents=True, exist_ok=True)
        note = root / "corpus" / "n.txt"
        note.write_text("hello workflow", encoding="utf-8")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
        )
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.jobs = JobRuntime(self.job_store, self.gateway, ResourceManager(2))
        self.store = WorkflowStore(self.db)
        self.store.initialize()
        self.runtime = WorkflowRuntime(self.store, self.gateway, job_runtime=self.jobs)
        self.note = note

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_advance_one_step_then_continue(self) -> None:
        wf = self.runtime.create(
            name="t",
            steps=[
                WorkflowStepDef(
                    step_id="s0",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
            ],
        )
        mid = self.runtime.advance_one_step(wf.workflow_id)
        self.assertEqual(mid.state, WorkflowState.RUNNING)
        self.assertEqual(mid.current_step, 1)
        done = self.runtime.advance_one_step(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)
        self.assertEqual(done.current_step, 2)

    def test_run_still_completes_all(self) -> None:
        wf = self.runtime.create(
            name="all",
            steps=[
                WorkflowStepDef(
                    step_id="s0",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
            ],
        )
        done = self.runtime.run(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)

    def test_enqueue_advance_creates_durable_job(self) -> None:
        wf = self.runtime.create(
            name="enq",
            steps=[
                WorkflowStepDef(
                    step_id="s0",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
            ],
        )
        job = self.runtime.enqueue_advance(wf.workflow_id)
        self.assertEqual(job.capability_id, "workflow.advance")
        self.assertIn("workflow.advance", EXTERNAL_WORKER_CAPABILITIES)
        self.assertEqual(pool_for_capability("workflow.advance"), "workflow")
        self.assertEqual(job.arguments.get("workflow_id"), wf.workflow_id)
        self.assertTrue((job.idempotency_key or "").startswith(f"workflow:advance:{wf.workflow_id}:"))
        refreshed = self.store.get(wf.workflow_id)
        assert refreshed is not None
        self.assertEqual(refreshed.state, WorkflowState.RUNNING)
        # Idempotent: same step index returns same job
        again = self.runtime.enqueue_advance(wf.workflow_id)
        self.assertEqual(again.job_id, job.job_id)

    def test_worker_handler_advances_one_and_enqueues_next(self) -> None:
        from Data.modules.workers.entrypoints.workflow import _handler

        wf = self.runtime.create(
            name="wh",
            steps=[
                WorkflowStepDef(
                    step_id="s0",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
            ],
        )
        job = self.runtime.enqueue_advance(wf.workflow_id)
        # Simulate claim: mark RUNNING so handler can complete it
        from Data.modules.jobs.states import JobState

        claimed = self.job_store.transition(job.job_id, JobState.RUNNING)
        ctx = {
            "settings": type("S", (), {"database_path": self.db})(),
            "job_store": self.job_store,
            "job_runtime": self.jobs,
            "gateway": self.gateway,
        }
        _handler(ctx, claimed)
        mid = self.store.get(wf.workflow_id)
        assert mid is not None
        self.assertEqual(mid.state, WorkflowState.RUNNING)
        self.assertEqual(mid.current_step, 1)
        jobs = self.job_store.list(limit=20)
        cont = [
            j
            for j in jobs
            if j.capability_id == "workflow.advance"
            and j.job_id != job.job_id
            and (j.idempotency_key or "").endswith(":1")
        ]
        self.assertEqual(len(cont), 1)
        done_job = self.job_store.get(job.job_id)
        assert done_job is not None
        self.assertEqual(done_job.state, JobState.COMPLETED)

    def test_schedule_workflow_enqueues_not_inline(self) -> None:
        schedules = ScheduleStore(self.db)
        schedules.initialize()
        runner = ScheduleRunner(schedules, jobs=self.jobs, workflows=self.runtime)
        schedule = schedules.create(
            name="wf",
            target_kind=ScheduleTargetKind.WORKFLOW,
            target_ref="file.read",
            interval_seconds=60,
            target_payload={"arguments": {"path": str(self.note)}},
            start_after_seconds=0,
        )
        fired = runner.tick(execute=False)
        self.assertEqual(len(fired), 1)
        self.assertTrue(fired[0]["ok"])
        self.assertFalse(fired[0].get("executed_inline"))
        self.assertIn("job_id", fired[0])
        jobs = self.job_store.list(limit=20)
        self.assertTrue(any(j.capability_id == "workflow.advance" for j in jobs))
        # Workflow should be RUNNING but not yet completed (worker hasn't claimed)
        wf_id = fired[0]["workflow_id"]
        record = self.store.get(wf_id)
        assert record is not None
        self.assertEqual(record.state, WorkflowState.RUNNING)
        self.assertEqual(record.current_step, 0)
        _ = schedule


class MarketSimExternalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "ms.db"
        self.markets = root / "markets"
        self.markets.mkdir(parents=True)
        from Data.modules.market_sim import MarketSimControlPlane
        from Data.modules.market_sim.store import MarketSimStore
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
        from Data.modules.execution import ExecutionGateway, build_default_catalog

        self.store = MarketSimStore(self.db)
        self.store.initialize()
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.jobs = JobRuntime(self.job_store, self.gateway, ResourceManager(2))

        class _Feat:
            market_sim_enabled = True

        class _MS:
            markets_root = str(self.markets)
            bars_per_slice = 10
            default_initial_cash = 100_000.0

        class _S:
            features = _Feat()
            market_sim = _MS()
            database_path = self.db

        self.plane = MarketSimControlPlane.from_settings(_S())
        self.plane.bind_job_runtime(self.jobs)
        self.plane.enabled = True

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_start_background_externalize_does_not_spawn_thread(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            self.plane.start_background()
        thread = self.plane.worker._thread
        self.assertTrue(thread is None or not thread.is_alive())

    def test_start_run_enqueues_market_sim_advance(self) -> None:
        from Data.modules.market_sim.types import RunStatus, SimRun
        from Data.modules.market_sim.store import utc_now

        now = utc_now()
        run = SimRun(
            run_id="run-ext-1",
            status=RunStatus.CREATED.value,
            source_id="src",
            strategy_id=None,
            strategy_version=None,
            symbol="BTC",
            timeframe="1h",
            start_ts=now,
            end_ts=now,
            data_hash="h",
            seed=1,
            created_at=now,
            updated_at=now,
        )
        self.store.create_run(run)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            out = self.plane.start_run(run.run_id)
        self.assertEqual(out["status"], RunStatus.QUEUED.value)
        jobs = self.job_store.list(limit=20)
        self.assertTrue(any(j.capability_id == "market_sim.advance" for j in jobs))
        self.assertTrue(
            any(
                (j.arguments or {}).get("simulation_id") == run.run_id
                for j in jobs
                if j.capability_id == "market_sim.advance"
            )
        )
        self.assertIn("market_sim.advance", EXTERNAL_WORKER_CAPABILITIES)
        self.assertEqual(pool_for_capability("market_sim.advance"), "market_sim")


if __name__ == "__main__":
    unittest.main()
