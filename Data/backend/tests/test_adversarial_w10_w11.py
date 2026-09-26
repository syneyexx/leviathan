"""W10 tool-gateway + W11 durable execution adversarial regressions.

Canonical owners:
  - ExecutionGateway — Data/modules/execution/gateway.py
  - JobRuntime / JobStore leases — Data/modules/jobs/
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager, StaleLeaseError
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore


def _artifact_count(artifacts: ArtifactStore) -> int:
    with artifacts.connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()
    return int(row[0] if row else 0)


class GatewayUnauthorizedAndIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "gw.db"
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
        self.runtime = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.observations = ObservationStore(self.db_path)
        self.observations.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
            observation_store=self.observations,
        )

    def tearDown(self) -> None:
        self.runtime.shutdown()
        self.tmp.cleanup()

    def test_w10_approved_by_user_boolean_is_not_authority(self) -> None:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={
                    "content": "sneak",
                    "filename": "sneak.txt",
                    "approved_by_user": True,
                },
            )
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertEqual(result.telemetry.get("reason"), "approval_required")
        self.assertEqual(_artifact_count(self.artifacts), 0)

    def test_w10_forged_and_consumed_approval_rejected(self) -> None:
        forged = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "x", "filename": "x.txt"},
                approval_id="forged-approval-id",
            )
        )
        self.assertEqual(forged.status, CapabilityStatus.REJECTED)
        self.assertEqual(forged.telemetry.get("reason"), "approval_denied")

        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
        )
        approved = self.approvals.approve(pending.approval_id, decided_by="operator")
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "once", "filename": "once.txt"},
                approval_id=approved.approval_id,
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)
        reused = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "twice", "filename": "twice.txt"},
                approval_id=approved.approval_id,
            )
        )
        self.assertEqual(reused.status, CapabilityStatus.REJECTED)
        self.assertEqual(reused.telemetry.get("reason"), "approval_denied")
        self.assertEqual(_artifact_count(self.artifacts), 1)

    def test_w10_idempotent_tool_invocation_does_not_double_side_effect(self) -> None:
        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
        )
        approved = self.approvals.approve(pending.approval_id, decided_by="operator")
        key = "gw:artifact:idem-1"
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "same-payload", "filename": "idem.txt"},
                approval_id=approved.approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)
        assert first.output is not None
        artifact_id = first.output.get("artifact_id") or first.output.get("id")

        # Second call must replay without creating another artifact / effect.
        second = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "same-payload", "filename": "idem.txt"},
                approval_id="should-not-matter",
                idempotency_key=key,
            )
        )
        self.assertEqual(second.status, CapabilityStatus.COMPLETED)
        self.assertTrue(second.telemetry.get("idempotent_replay"))
        self.assertEqual(_artifact_count(self.artifacts), 1)
        # Only one COMPLETED effect for this idempotency key in the durable ledger.
        effects = [
            e
            for e in self.observations.list_effects(limit=50)
            if e.status == "COMPLETED" and e.capability_id == "artifact.create_text"
        ]
        self.assertEqual(len(effects), 1)
        self.assertEqual(self.gateway.telemetry.get("idempotent_replays"), 1)
        if artifact_id:
            self.assertEqual(
                (second.output or {}).get("artifact_id") or (second.output or {}).get("id"),
                artifact_id,
            )

    def test_w10_idempotent_replay_survives_new_gateway_instance(self) -> None:
        pending = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
        )
        approved = self.approvals.approve(pending.approval_id, decided_by="operator")
        key = "gw:artifact:durable-1"
        first = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "durable", "filename": "d.txt"},
                approval_id=approved.approval_id,
                idempotency_key=key,
            )
        )
        self.assertEqual(first.status, CapabilityStatus.COMPLETED)

        gateway2 = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.runtime,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
            observation_store=ObservationStore(self.db_path),
        )
        replay = gateway2.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "durable", "filename": "d.txt"},
                idempotency_key=key,
            )
        )
        self.assertEqual(replay.status, CapabilityStatus.COMPLETED)
        self.assertTrue(replay.telemetry.get("idempotent_replay"))
        self.assertEqual(replay.telemetry.get("idempotent_replay_source"), "observation_store")
        self.assertEqual(_artifact_count(self.artifacts), 1)


class DurableLeaseFenceAndRecoveryTests(unittest.TestCase):
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
        path = self.root / "note.txt"
        path.write_text("recover-me", encoding="utf-8")
        self.note = path
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
        )
        self.store = JobStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_w11_stale_worker_cannot_complete_after_lease_takeover(self) -> None:
        stale = JobRuntime(
            self.store,
            self.gateway,
            ResourceManager(max_job_concurrency=2),
            worker_id="worker-stale",
            lease_ttl_seconds=30.0,
        )
        job = stale.enqueue(
            capability_id="file.read",
            arguments={"path": str(self.note)},
        )
        claimed = self.store.claim_next_queued(
            worker_id="worker-stale",
            lease_ttl_seconds=30.0,
        )
        assert claimed is not None
        self.assertEqual(claimed.job_id, job.job_id)
        self.assertEqual(claimed.lease_owner, "worker-stale")

        # Force expiry and let a fresh worker take over while still RUNNING.
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
                (past, job.job_id),
            )
        taken = self.store.claim_next_queued(
            worker_id="worker-fresh",
            lease_ttl_seconds=30.0,
            reclaim_expired=True,
        )
        assert taken is not None
        self.assertEqual(taken.job_id, job.job_id)
        self.assertEqual(taken.lease_owner, "worker-fresh")

        with self.assertRaises(StaleLeaseError):
            self.store.transition(
                job.job_id,
                JobState.COMPLETED,
                result={"fabricated": True},
                expected_lease_owner="worker-stale",
            )
        current = self.store.get(job.job_id)
        assert current is not None
        self.assertEqual(current.state, JobState.RUNNING)
        self.assertEqual(current.lease_owner, "worker-fresh")
        self.assertIsNone(current.result)

        # Fresh owner may complete under its fence.
        done = self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"ok": True},
            expected_lease_owner="worker-fresh",
        )
        self.assertEqual(done.state, JobState.COMPLETED)

    def test_w11_crash_recovery_requeues_without_fabricating_success(self) -> None:
        runtime = JobRuntime(
            self.store,
            self.gateway,
            ResourceManager(max_job_concurrency=1),
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
        )
        job = runtime.enqueue(
            capability_id="file.read",
            arguments={"path": str(self.note)},
        )
        claimed = self.store.claim_next_queued(worker_id="worker-a", lease_ttl_seconds=30.0)
        assert claimed is not None
        self.assertEqual(claimed.state, JobState.RUNNING)

        # Simulate crash: lease expires while still RUNNING with no result.
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
                (past, job.job_id),
            )

        recovered = runtime.recover_expired_leases()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].job_id, job.job_id)
        self.assertEqual(recovered[0].state, JobState.RETRY_WAIT)
        self.assertNotEqual(recovered[0].state, JobState.COMPLETED)
        self.assertIsNone(recovered[0].result)

        # Resume on a new worker identity — honest re-execution, not fabricated success.
        runtime_b = JobRuntime(
            self.store,
            self.gateway,
            ResourceManager(max_job_concurrency=1),
            worker_id="worker-b",
            lease_ttl_seconds=30.0,
        )
        done = runtime_b.process_next()
        assert done is not None
        self.assertEqual(done.state, JobState.COMPLETED)
        assert done.result is not None
        self.assertIn("recover-me", done.result["output"]["content"])


if __name__ == "__main__":
    unittest.main()
