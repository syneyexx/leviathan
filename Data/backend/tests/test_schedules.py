from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.modules.schedules import (
    ScheduleRunner,
    ScheduleStore,
    ScheduleTargetKind,
)
from Data.modules.schedules.store import utc_now
from Data.modules.workflows import WorkflowRuntime, WorkflowStore


class ScheduleRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "s.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="S", content="scheduled search needle", source="t")
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
        jobs = JobRuntime(JobStore(db), gateway, ResourceManager(1))
        jobs.store.initialize()
        workflows = WorkflowRuntime(WorkflowStore(db), gateway)
        workflows.store.initialize()
        self.store = ScheduleStore(db)
        self.store.initialize()
        self.runner = ScheduleRunner(self.store, jobs=jobs, workflows=workflows)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_tick_fires_due_job_schedule(self) -> None:
        schedule = self.store.create(
            name="search",
            target_kind=ScheduleTargetKind.JOB,
            target_ref="knowledge.search",
            interval_seconds=60,
            target_payload={"arguments": {"query": "scheduled search", "limit": 2}},
            start_after_seconds=0,
        )
        # Force due by rewriting next_run_at into the past via mark helper path:
        # create with start_after 0 is already due.
        fired = self.runner.tick()
        self.assertEqual(len(fired), 1)
        self.assertTrue(fired[0]["ok"])
        refreshed = self.store.get(schedule.schedule_id)
        assert refreshed is not None
        self.assertIsNotNone(refreshed.last_run_at)
        # Second tick should not fire until interval elapses.
        fired2 = self.runner.tick()
        self.assertEqual(fired2, [])


if __name__ == "__main__":
    unittest.main()
