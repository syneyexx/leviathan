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

    def test_cancel_running_requests_cooperative_cancel(self) -> None:
        """RUNNING jobs move to CANCEL_REQUESTED, not terminal CANCELLED."""
        job = self.store.create(capability_id="file.read", arguments={"path": "x"})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="test-worker")
        assert claimed is not None
        self.assertEqual(claimed.state, JobState.RUNNING)
        pending = self.jobs.cancel(claimed.job_id)
        self.assertEqual(pending.state, JobState.CANCEL_REQUESTED)
        self.assertIsNotNone(pending.cancel_requested_at)
        acked = self.store.ack_cancel(claimed.job_id)
        self.assertEqual(acked.state, JobState.CANCELLED)

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

    def test_stale_lease_cannot_complete_job(self) -> None:
        """W11: worker that lost lease fencing cannot mark COMPLETED."""
        from Data.modules.jobs import StaleLeaseError

        job = self.store.create(capability_id="file.read", arguments={"path": "x"})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="worker-a")
        assert claimed is not None
        self.assertEqual(claimed.lease_owner, "worker-a")
        # Simulate lease transfer / reclaim by another worker.
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_owner = ?, updated_at = ? WHERE job_id = ?",
                ("worker-b", "2099-01-01T00:00:00+00:00", claimed.job_id),
            )
        with self.assertRaises(StaleLeaseError):
            self.store.transition(
                claimed.job_id,
                JobState.COMPLETED,
                expected_lease_owner="worker-a",
            )
        still = self.store.get(claimed.job_id)
        assert still is not None
        self.assertEqual(still.state, JobState.RUNNING)
        self.assertEqual(still.lease_owner, "worker-b")


if __name__ == "__main__":
    unittest.main()
