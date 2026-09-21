from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, SideEffect, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import (
    InvalidJobTransition,
    JobRuntime,
    JobState,
    JobStore,
    ResourceManager,
    validate_job_transition,
)
from Data.modules.knowledge import HybridRetriever, KnowledgeStore


class JobTransitionTests(unittest.TestCase):
    def test_created_to_queued(self) -> None:
        validate_job_transition(JobState.CREATED, JobState.QUEUED)

    def test_failed_cannot_complete(self) -> None:
        with self.assertRaises(InvalidJobTransition):
            validate_job_transition(JobState.FAILED, JobState.COMPLETED)


class JobRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "jobs.db"
        self.artifacts = ArtifactStore(self.db_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(
            self.db_path,
            data_root=self.root / "corpus",
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        (self.root / "corpus").mkdir(parents=True, exist_ok=True)
        self.runtime_fn = FunctionRuntime(
            build_default_registry(), max_concurrency=2, warm_cache_size=1
        )
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime_fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
        )
        self.store = JobStore(self.db_path)
        self.store.initialize()
        self.resources = ResourceManager(max_job_concurrency=1)
        self.jobs = JobRuntime(self.store, self.gateway, self.resources)

    def tearDown(self) -> None:
        self.jobs.stop_background_worker()
        self.runtime_fn.shutdown()
        self.tmp.cleanup()

    def test_enqueue_and_process_read_job(self) -> None:
        path = self.root / "note.txt"
        path.write_text("job-hello", encoding="utf-8")
        job = self.jobs.enqueue(
            capability_id="file.read",
            arguments={"path": str(path)},
        )
        self.assertEqual(job.state, JobState.QUEUED)
        done = self.jobs.process_next()
        assert done is not None
        self.assertEqual(done.state, JobState.COMPLETED)
        assert done.result is not None
        self.assertIn("job-hello", done.result["output"]["content"])

    def test_write_job_fails_without_approval(self) -> None:
        job = self.jobs.enqueue(
            capability_id="artifact.create_text",
            arguments={"content": "x", "filename": "a.txt"},
        )
        done = self.jobs.process_next()
        assert done is not None
        self.assertEqual(done.state, JobState.FAILED)
        self.assertIn("approval", (done.error or "").lower())

    def test_write_job_with_approval_completes(self) -> None:
        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
        )
        approved = self.approvals.approve(pending.approval_id)
        job = self.jobs.enqueue(
            capability_id="artifact.create_text",
            arguments={"content": "job-artifact", "filename": "a.txt"},
            approval_id=approved.approval_id,
        )
        done = self.jobs.process_next()
        assert done is not None
        self.assertEqual(done.state, JobState.COMPLETED)

    def test_cancel_queued_job(self) -> None:
        job = self.jobs.enqueue(
            capability_id="file.read",
            arguments={"path": str(self.root / "missing.txt")},
        )
        cancelled = self.jobs.cancel(job.job_id)
        self.assertEqual(cancelled.state, JobState.CANCELLED)
        self.assertIsNone(self.jobs.process_next())

    def test_resource_limit_blocks_second_slot(self) -> None:
        self.assertTrue(self.resources.try_acquire("holder"))
        job = self.jobs.enqueue(
            capability_id="file.read",
            arguments={"path": str(self.root / "x.txt")},
        )
        self.assertIsNone(self.jobs.process_next())
        still = self.jobs.get(job.job_id)
        assert still is not None
        self.assertEqual(still.state, JobState.QUEUED)
        self.resources.release("holder")
        # Now process can proceed (may FAIL on missing file — still proves slot freed).
        processed = self.jobs.process_next()
        assert processed is not None
        self.assertIn(processed.state, {JobState.COMPLETED, JobState.FAILED})


if __name__ == "__main__":
    unittest.main()
