"""Wave 19 — autonomous operating scheduler pipeline + backpressure."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.modules.schedules import (
    OPERATING_STAGES,
    ScheduleRunner,
    ScheduleStore,
    ensure_operating_pipeline,
    pause_operating_pipeline,
    queue_is_saturated,
)
from Data.modules.workflows import WorkflowRuntime, WorkflowStore


class OperatingPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "s.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(db)
        obs.initialize()
        gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        self.job_store = JobStore(db)
        self.job_store.initialize()
        self.jobs = JobRuntime(self.job_store, gateway, ResourceManager(1))
        workflows = WorkflowRuntime(WorkflowStore(db), gateway)
        workflows.store.initialize()
        self.store = ScheduleStore(db)
        self.store.initialize()
        self.runner = ScheduleRunner(self.store, jobs=self.jobs, workflows=workflows)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_ensure_pipeline_idempotent(self) -> None:
        plan1 = ensure_operating_pipeline(
            self.store,
            pipeline_id="paper-ops",
            universe=["BTCUSDT"],
            strategy_id="strat-1",
        )
        self.assertEqual(len(plan1.schedules), len(OPERATING_STAGES))
        stages = {s["stage"] for s in plan1.schedules}
        self.assertIn("research", stages)
        self.assertIn("paper_candidate", stages)
        self.assertIn("lesson_consolidation", stages)
        plan2 = ensure_operating_pipeline(
            self.store,
            pipeline_id="paper-ops",
            universe=["BTCUSDT"],
            strategy_id="strat-1",
        )
        self.assertTrue(all(s["reused"] for s in plan2.schedules))
        self.assertEqual(
            {s["schedule_id"] for s in plan1.schedules},
            {s["schedule_id"] for s in plan2.schedules},
        )

    def test_no_duplicate_research_on_double_tick(self) -> None:
        ensure_operating_pipeline(self.store, pipeline_id="dup", start_after_seconds=0)
        # Force only research stage due; others advance next_run far ahead.
        for row in self.store.list(limit=100):
            if "research" not in row.name:
                self.store.mark_ran(row.schedule_id)
        fired1 = self.runner.tick()
        research_jobs = [
            r for r in fired1 if r.get("ok") and "research" in str(r.get("schedule_id", ""))
        ]
        # Collect job ids for research capability.
        research_fire = [
            r
            for r in fired1
            if r.get("ok") and r.get("target") == "job"
        ]
        self.assertTrue(research_fire)
        job_ids_first = {r["job_id"] for r in research_fire}
        # Immediate second tick: schedules not due → no new fire.
        fired2 = self.runner.tick()
        self.assertEqual(fired2, [])
        # Force same occurrence key by rewriting next_run_at into the past without mark_ran.
        research_sched = next(s for s in self.store.list(limit=100) if s.name.endswith(":research"))
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE schedules SET next_run_at = ? WHERE schedule_id = ?",
                ("2000-01-01T00:00:00+00:00", research_sched.schedule_id),
            )
        # But occurrence uses next_run_at; after mark_ran it changed. Force identical
        # occurrence via payload to prove idempotency key suppresses duplicate.
        with self.store.connect() as conn:
            import json

            conn.execute(
                "UPDATE schedules SET target_payload_json = ?, next_run_at = ? WHERE schedule_id = ?",
                (
                    json.dumps({"arguments": {}, "occurrence": "fixed-occ-1"}),
                    "2000-01-01T00:00:00+00:00",
                    research_sched.schedule_id,
                ),
            )
        # First fire with fixed occurrence.
        # Reset last_run so idempotent_reuse detection works on second delivery.
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE schedules SET last_run_at = NULL, next_run_at = ? WHERE schedule_id = ?",
                ("2000-01-01T00:00:00+00:00", research_sched.schedule_id),
            )
        f_a = self.runner.tick()
        self.assertTrue(any(r.get("ok") for r in f_a))
        job_a = next(r["job_id"] for r in f_a if r.get("ok"))
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE schedules SET next_run_at = ? WHERE schedule_id = ?",
                ("2000-01-01T00:00:00+00:00", research_sched.schedule_id),
            )
        f_b = self.runner.tick()
        self.assertTrue(any(r.get("ok") for r in f_b))
        job_b = next(r["job_id"] for r in f_b if r.get("ok"))
        self.assertEqual(job_a, job_b)
        self.assertGreaterEqual(int(self.runner.telemetry.get("duplicates_suppressed", 0)), 1)

    def test_backpressure_when_queue_saturated(self) -> None:
        ensure_operating_pipeline(self.store, pipeline_id="bp", start_after_seconds=0)
        self.runner.configure_backpressure(limit=2)
        # Saturate queue.
        for i in range(3):
            self.jobs.enqueue(
                capability_id="knowledge.search",
                arguments={"query": f"q{i}"},
                idempotency_key=f"sat-{i}",
            )
        self.assertTrue(queue_is_saturated(self.job_store, limit=2))
        out = self.runner.tick()
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].get("backpressure"))
        self.assertGreaterEqual(int(self.runner.telemetry.get("backpressure_skips", 0)), 1)

    def test_pause_pipeline(self) -> None:
        ensure_operating_pipeline(self.store, pipeline_id="pause-me")
        paused = pause_operating_pipeline(self.store, pipeline_id="pause-me")
        self.assertEqual(len(paused["paused_schedule_ids"]), len(OPERATING_STAGES))


if __name__ == "__main__":
    unittest.main()
