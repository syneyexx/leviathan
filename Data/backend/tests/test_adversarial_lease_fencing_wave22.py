"""WAVE 22 — adversarial lease fencing across worker/executor transition paths.

Stale worker A loses lease; worker B completes; A returns late and must not
overwrite canonical COMPLETED/FAILED/CANCELLED job truth.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs.leases import (
    LeaseFenceError,
    fenced_transition,
    make_lease_bound_checks,
    observe_job_cancel_state,
    require_lease_heartbeat,
)
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState, StaleLeaseError
from Data.modules.jobs.store import JobStore
from Data.modules.mcp.execution import McpExecutionExecutor
from Data.modules.model_download.executor import ModelDownloadExecutor
from Data.modules.provider_io.executor import ProviderIoExecutor
from Data.modules.provider_io.types import ProviderExecutionResult


def _runtime(db: Path, *, worker_id: str = "runtime") -> JobRuntime:
    store = JobStore(db)
    store.initialize()
    gateway = ExecutionGateway(catalog=build_default_catalog())
    return JobRuntime(
        store,
        gateway,
        ResourceManager(max_job_concurrency=4),
        worker_id=worker_id,
        lease_ttl_seconds=30.0,
    )


def _steal_lease(store: JobStore, job_id: str, *, new_owner: str) -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
    with store.connect() as conn:
        conn.execute(
            "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
            (new_owner, past, job_id),
        )
    # Give B a live lease so B can complete under fencing.
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")
    with store.connect() as conn:
        conn.execute(
            "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
            (new_owner, future, job_id),
        )


class FencedTransitionHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fenced_transition_records_telemetry_on_stale(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        claimed = self.store.claim_next_queued(worker_id="worker-a", lease_ttl_seconds=30.0)
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "b"},
            expected_lease_owner="worker-b",
        )
        ctx: dict = {}
        tele: dict = {}
        out = fenced_transition(
            self.store,
            job.job_id,
            JobState.FAILED,
            worker_id="worker-a",
            ctx=ctx,
            telemetry=tele,
            error="late_stale",
            result={"from": "a"},
        )
        self.assertIsNone(out)
        self.assertGreaterEqual(int(tele.get("stale_lease_fenced", 0)), 1)
        self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "b")


class ProviderIoLeaseRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stale_provider_io_cannot_overwrite_completed(self) -> None:
        job = self.runtime.enqueue(
            capability_id="provider.chat.complete",
            arguments={
                "provider": "fake",
                "capability": "chat.complete",
                "credential_ref": "none",
                "payload": {"endpoint": "http://127.0.0.1:9", "messages": []},
            },
            worker_pool="provider_io",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="provider_io", worker_id="worker-a", lease_ttl_seconds=30.0
        )
        assert claimed is not None

        # B takes over and completes while A is still "working".
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "worker-b", "status": "succeeded"},
            expected_lease_owner="worker-b",
        )

        fake_result = ProviderExecutionResult(
            status="succeeded",
            provider="fake",
            model="m",
            content="late-from-a",
        )

        class _Adapter:
            def execute(self, request, **kwargs):
                return fake_result

        executor = ProviderIoExecutor(db_path=str(self.db))
        try:
            # Force unknown capability path to use our adapter via capability map.
            executor._adapters["chat.complete"] = _Adapter()  # type: ignore[assignment]
            ctx = {
                "job_store": self.store,
                "worker_id": "worker-a",
                "lease_ttl_seconds": 30.0,
            }
            # Heartbeat will fail (wrong owner) before execute — cancel/fence path.
            # Patch cancel_check to allow execute so we exercise post-side-effect COMPLETED fence.
            with mock.patch(
                "Data.modules.provider_io.executor.make_lease_bound_checks",
                return_value=(lambda: False, lambda: None),
            ):
                out = executor.execute_job(ctx, claimed)
        finally:
            executor.close()

        self.assertEqual(out.get("status"), "succeeded")
        self.assertEqual(out.get("content"), "late-from-a")
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "worker-b")
        self.assertNotEqual((final.result or {}).get("content"), "late-from-a")
        self.assertGreaterEqual(int(executor.policy.telemetry.get("stale_lease_fenced", 0)), 1)

    def test_provider_io_lease_fence_after_side_effect_does_not_fail_job(self) -> None:
        job = self.runtime.enqueue(
            capability_id="provider.http",
            arguments={
                "provider": "fake",
                "capability": "http",
                "credential_ref": "none",
                "payload": {"url": "http://127.0.0.1:9"},
            },
            worker_pool="provider_io",
        )
        claimed = self.store.claim_next_for_pool(
            pool_id="provider_io", worker_id="worker-a", lease_ttl_seconds=30.0
        )
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "worker-b"},
            expected_lease_owner="worker-b",
        )

        class _Adapter:
            def execute(self, request, **kwargs):
                raise LeaseFenceError("mid-flight", job_id=job.job_id, worker_id="worker-a")

        executor = ProviderIoExecutor(db_path=str(self.db))
        try:
            executor._adapters["http"] = _Adapter()  # type: ignore[assignment]
            ctx = {
                "job_store": self.store,
                "worker_id": "worker-a",
                "lease_ttl_seconds": 30.0,
            }
            with mock.patch(
                "Data.modules.provider_io.executor.make_lease_bound_checks",
                return_value=(lambda: False, lambda: None),
            ):
                out = executor.execute_job(ctx, claimed)
        finally:
            executor.close()

        self.assertEqual(out.get("status"), "failed")
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "worker-b")
        self.assertGreaterEqual(int(executor.policy.telemetry.get("stale_lease_fenced", 0)), 1)


class McpLeaseRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stale_mcp_cannot_overwrite_completed(self) -> None:
        job = self.runtime.enqueue(
            capability_id="mcp.call",
            arguments={"server_id": "s1", "tool_name": "echo", "arguments": {}},
            worker_pool="mcp_execution",
        )
        claimed = self.store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
            capability_ids={"mcp.call"},
        )
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "worker-b"},
            expected_lease_owner="worker-b",
        )

        executor = McpExecutionExecutor(db_path=str(self.db))
        # Seed a fake server config so we get past lookup, then fence on heartbeat.
        with mock.patch.object(executor.store, "get_server", return_value=mock.Mock()):
            ctx = {
                "job_store": self.store,
                "worker_id": "worker-a",
                "lease_ttl_seconds": 30.0,
            }
            out = executor.execute_job(ctx, claimed)

        self.assertEqual(out.get("status"), "failed")
        self.assertEqual((out.get("error") or {}).get("code"), "LEASE_FENCE")
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "worker-b")
        self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)


class ModelDownloadLeaseRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stale_model_download_cannot_overwrite_completed(self) -> None:
        job = self.runtime.enqueue(
            capability_id="model_download.start",
            arguments={
                "download_id": "dl-1",
                "source": "huggingface",
                "repository_id": "org/model",
            },
            worker_pool="model_download",
        )
        claimed = self.store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=60.0,
            capability_ids={"model_download.start"},
        )
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "worker-b"},
            expected_lease_owner="worker-b",
        )

        executor = ModelDownloadExecutor(db_path=str(self.db))
        try:
            ctx = {
                "job_store": self.store,
                "worker_id": "worker-a",
                "lease_ttl_seconds": 60.0,
            }
            with mock.patch.object(
                executor,
                "_run_hf",
                return_value={"status": "succeeded", "model_id": "late-a"},
            ), mock.patch(
                "Data.modules.model_download.executor.make_lease_bound_checks",
                return_value=(lambda: False, lambda: None),
            ):
                out = executor.execute_job(ctx, claimed)
        finally:
            executor.close()

        self.assertEqual(out.get("status"), "succeeded")
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "worker-b")
        self.assertNotEqual((final.result or {}).get("model_id"), "late-a")
        self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)

    def test_model_download_lease_fence_after_side_effect_no_overwrite(self) -> None:
        job = self.runtime.enqueue(
            capability_id="model_download.start",
            arguments={"download_id": "dl-2", "source": "ollama", "repository_id": "llama"},
            worker_pool="model_download",
        )
        claimed = self.store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=60.0,
            capability_ids={"model_download.start"},
        )
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "worker-b"},
            expected_lease_owner="worker-b",
        )

        executor = ModelDownloadExecutor(db_path=str(self.db))
        try:
            ctx = {
                "job_store": self.store,
                "worker_id": "worker-a",
                "lease_ttl_seconds": 60.0,
            }

            def _boom(*_a, **_k):
                raise LeaseFenceError("lost mid pull", job_id=job.job_id, worker_id="worker-a")

            with mock.patch.object(executor, "_run_ollama", side_effect=_boom), mock.patch(
                "Data.modules.model_download.executor.make_lease_bound_checks",
                return_value=(lambda: False, lambda: None),
            ):
                out = executor.execute_job(ctx, claimed)
        finally:
            executor.close()

        self.assertEqual(out.get("status"), "failed")
        self.assertEqual((out.get("error") or {}).get("code"), "LEASE_FENCE")
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "worker-b")


class EntrypointLeaseRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_maintenance_stale_cannot_overwrite_completed(self) -> None:
        from Data.modules.workers.entrypoints.maintenance import _handler

        job = self.store.create(capability_id="system.maintenance", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
            capability_ids={"system.maintenance"},
        )
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"recovered": 99, "from": "b"},
            expected_lease_owner="worker-b",
        )
        ctx = {
            "job_store": self.store,
            "worker_id": "worker-a",
            "admission": mock.Mock(recover_expired=mock.Mock()),
            "registry": mock.Mock(reconcile_stale=mock.Mock()),
        }
        out = _handler(ctx, claimed)
        self.assertEqual(out.get("recovered"), 0)
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "b")
        self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)

    def test_knowledge_commit_stale_cannot_overwrite_completed(self) -> None:
        from Data.modules.workers.entrypoints.knowledge_commit import _handler

        job = self.runtime.enqueue(
            capability_id="knowledge.commit",
            arguments={"artifact": {"title": "t", "artifact_id": "a1"}},
            worker_pool="knowledge_commit",
        )
        claimed = self.store.claim_next_queued(
            worker_id="worker-a",
            lease_ttl_seconds=30.0,
            capability_ids={"knowledge.commit"},
        )
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"from": "b"},
            expected_lease_owner="worker-b",
        )

        fake_result = mock.Mock(
            accepted=False,
            ack_status="REJECTED",
            message="nope",
            public_dict=lambda: {"accepted": False},
        )
        settings = mock.Mock(database_path=self.db, knowledge_database_path=self.db)
        ctx = {
            "job_store": self.store,
            "worker_id": "worker-a",
            "settings": settings,
        }
        with mock.patch("Data.modules.db_commit.producer.CommitProducer") as producer_cls:
            producer_cls.return_value.submit.return_value = fake_result
            out = _handler(ctx, claimed)
        self.assertEqual((out or {}).get("accepted"), False)
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("from"), "b")
        self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)


class FailClosedPreservedTests(unittest.TestCase):
    """Cancel-read / heartbeat fail-closed contracts must remain."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cancel_read_failure_still_fail_closed(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        broken = mock.Mock()
        broken.get.side_effect = RuntimeError("db locked")
        self.assertTrue(observe_job_cancel_state(broken, job.job_id, worker_id="w1"))

    def test_heartbeat_failure_still_raises_fence(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        claimed = self.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=30.0)
        assert claimed is not None
        with self.assertRaises(LeaseFenceError):
            require_lease_heartbeat(
                self.store,
                job.job_id,
                worker_id="other",
                ttl_seconds=30.0,
            )

    def test_shared_checks_align_for_executors(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        claimed = self.store.claim_next_queued(worker_id="prov-1", lease_ttl_seconds=30.0)
        assert claimed is not None
        ctx: dict = {"worker_id": "prov-1"}
        cancel_check, heartbeat = make_lease_bound_checks(
            ctx, self.store, job.job_id, worker_id="prov-1", ttl_seconds=30.0
        )
        self.assertFalse(cancel_check())
        heartbeat()
        _steal_lease(self.store, job.job_id, new_owner="thief")
        self.assertTrue(cancel_check())
        with self.assertRaises(LeaseFenceError):
            heartbeat()


class DirectStoreFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.store = JobStore(self.db)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_loses_lease_still_running_cannot_complete(self) -> None:
        job = self.store.create(capability_id="file.read", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="worker-a", lease_ttl_seconds=30.0)
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        with self.assertRaises(StaleLeaseError):
            self.store.transition(
                job.job_id,
                JobState.COMPLETED,
                result={"owner": "a"},
                expected_lease_owner="worker-a",
            )
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.RUNNING)
        self.assertEqual(final.lease_owner, "worker-b")
        self.assertIsNone(final.result)

    def test_a_late_after_b_completed_fenced_helper_no_overwrite(self) -> None:
        job = self.store.create(capability_id="file.read", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="worker-a", lease_ttl_seconds=30.0)
        assert claimed is not None
        _steal_lease(self.store, job.job_id, new_owner="worker-b")
        done = self.store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"ok": True, "owner": "b"},
            expected_lease_owner="worker-b",
        )
        self.assertEqual(done.state, JobState.COMPLETED)
        ctx: dict = {}
        out = fenced_transition(
            self.store,
            job.job_id,
            JobState.FAILED,
            worker_id="worker-a",
            ctx=ctx,
            error="late-a",
            result={"owner": "a"},
        )
        self.assertIsNone(out)
        self.assertGreaterEqual(int(ctx.get("stale_lease_fenced", 0)), 1)
        final = self.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("owner"), "b")


if __name__ == "__main__":
    unittest.main()
