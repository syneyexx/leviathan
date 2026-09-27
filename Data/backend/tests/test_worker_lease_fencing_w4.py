"""Wave 4 WORKER-001..008 — worker lease fencing (fail closed)."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway, build_default_catalog
from Data.modules.jobs.leases import (
    LeaseFenceError,
    make_lease_bound_checks,
    observe_job_cancel_state,
    require_lease_heartbeat,
)
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.workers.admission import ResourceAdmission, ResourceClass
from Data.modules.workers.loop import _default_gateway_execute, run_pool_loop
from Data.modules.workers.registry import WorkerRegistry
from Data.modules.workers.settings import WorkerSettings


def _runtime(db: Path, *, worker_id: str = "test-runtime") -> JobRuntime:
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


class LeaseHelperUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)
        self.store = self.runtime.store

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_003_cancel_read_failure_fail_closed(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        broken = mock.Mock()
        broken.get.side_effect = RuntimeError("db locked")
        self.assertTrue(observe_job_cancel_state(broken, job.job_id, worker_id="w1"))

    def test_worker_002_heartbeat_failure_raises_fence(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        claimed = self.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=30.0)
        assert claimed is not None
        fence = {"lease_lost": threading.Event(), "job_cancel_fence": threading.Event()}
        with self.assertRaises(LeaseFenceError):
            require_lease_heartbeat(
                self.store,
                job.job_id,
                worker_id="other-worker",
                ttl_seconds=30.0,
                ctx=fence,
            )
        self.assertTrue(fence["lease_lost"].is_set())
        self.assertTrue(fence["job_cancel_fence"].is_set())

    def test_worker_005_006_007_shared_checks_align(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "x"})
        claimed = self.store.claim_next_queued(worker_id="prov-1", lease_ttl_seconds=30.0)
        assert claimed is not None
        ctx: dict = {
            "lease_lost": threading.Event(),
            "job_cancel_fence": threading.Event(),
            "lease_ttl_seconds": 30.0,
            "worker_id": "prov-1",
        }
        cancel_check, heartbeat = make_lease_bound_checks(
            ctx, self.store, job.job_id, worker_id="prov-1", ttl_seconds=30.0
        )
        self.assertFalse(cancel_check())
        heartbeat()  # proves lease

        # Store read failure → fail closed
        broken = mock.Mock()
        broken.get.side_effect = OSError("io")
        broken.heartbeat_lease.side_effect = OSError("io")
        cancel2, hb2 = make_lease_bound_checks(
            ctx, broken, job.job_id, worker_id="prov-1", ttl_seconds=30.0
        )
        self.assertTrue(cancel2())
        with self.assertRaises(LeaseFenceError):
            hb2()


class Worker001AcquireNoSwallowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db, worker_id="runtime-a")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_001_runtime_does_not_execute_without_lease(self) -> None:
        """Lease held by another worker → fence, no gateway side effect."""
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "owned"})
        claimed = self.runtime.store.claim_next_queued(
            worker_id="other-owner", lease_ttl_seconds=60.0
        )
        assert claimed is not None
        executed = {"n": 0}

        def _boom(_req: CapabilityRequest):
            executed["n"] += 1
            raise AssertionError("gateway must not run without lease")

        with mock.patch.object(self.runtime.gateway, "execute", side_effect=_boom):
            # Force local worker to attempt execute on an already-claimed job.
            out = self.runtime._execute_claimed(claimed)
        self.assertEqual(executed["n"], 0)
        self.assertGreaterEqual(int(self.runtime.telemetry.get("stale_lease_fenced", 0)), 1)
        current = self.runtime.store.get(job.job_id)
        assert current is not None
        self.assertEqual(current.lease_owner, "other-owner")
        self.assertEqual(current.state, JobState.RUNNING)
        self.assertIsNotNone(out)


class Worker004GatewayFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db, worker_id="gw-worker")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_004_gateway_stops_after_lease_loss(self) -> None:
        job = self.runtime.enqueue(capability_id="file.read", arguments={"text": "gw"})
        claimed = self.runtime.store.claim_next_queued(
            worker_id="gw-worker", lease_ttl_seconds=30.0
        )
        assert claimed is not None
        lease_lost = threading.Event()
        lease_lost.set()
        ctx = {"lease_lost": lease_lost, "job_cancel_fence": threading.Event()}

        # Steal lease so heartbeat also fails.
        with self.runtime.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_owner = ?, lease_expires_at = ? WHERE job_id = ?",
                ("thief", "2099-01-01T00:00:00+00:00", job.job_id),
            )

        executed = {"n": 0}

        def _exec(_req: CapabilityRequest):
            executed["n"] += 1
            return mock.Mock(
                status=CapabilityStatus.COMPLETED,
                output={"ok": True},
                public_dict=lambda: {"ok": True},
                error=None,
            )

        with mock.patch.object(self.runtime.gateway, "execute", side_effect=_exec):
            result = _default_gateway_execute(
                self.runtime,
                self.runtime.store,
                claimed,
                "gw-worker",
                30.0,
                ctx=ctx,
            )
        self.assertIsNone(result)
        self.assertEqual(executed["n"], 0)
        final = self.runtime.store.get(job.job_id)
        assert final is not None
        self.assertNotEqual(final.state, JobState.COMPLETED)


class Worker008AdmissionRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_008_admission_reject_recovery_does_not_swallow(self) -> None:
        job = self.runtime.enqueue(
            capability_id="file.read",
            arguments={"text": "admit"},
            worker_pool="general",
            resource_class="CPU_HEAVY",
            resource_request={"cpu_cores": 999},
        )
        registry = WorkerRegistry(self.db)
        registry.initialize()
        admission = ResourceAdmission(self.db)
        admission.initialize()
        # Force rejection by patching try_reserve.
        decision = mock.Mock(allowed=False, reason="RESOURCE_UNAVAILABLE", reservation_id="r0")

        saw_retry = {"ok": False}
        real_schedule = self.runtime.store.schedule_retry

        def _schedule(*a, **k):
            saw_retry["ok"] = True
            return real_schedule(*a, **k)

        def _ctx():
            return {
                "settings": mock.Mock(
                    database_path=self.db,
                    resources=mock.Mock(max_job_concurrency=2),
                ),
                "job_store": self.runtime.store,
                "job_runtime": self.runtime,
                "gateway": self.runtime.gateway,
                "registry": registry,
                "admission": admission,
                "worker_settings": WorkerSettings(
                    heartbeat_seconds=0.2,
                    lease_ttl_seconds=5.0,
                    poll_seconds=0.05,
                    pool_counts={"general": 1},
                ),
            }

        with mock.patch(
            "Data.modules.workers.loop.build_minimal_job_context", side_effect=_ctx
        ), mock.patch.object(admission, "try_reserve", return_value=decision), mock.patch.object(
            self.runtime.store, "schedule_retry", side_effect=_schedule
        ):
            run_pool_loop(pool_id="general", handler=lambda c, j: {}, once=True, max_jobs=1)
        self.assertTrue(saw_retry["ok"])
        final = self.runtime.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.RETRY_WAIT)
        self.assertIsNone(final.lease_owner)

    def test_worker_008_recovery_failure_fails_job(self) -> None:
        job = self.runtime.enqueue(
            capability_id="file.read",
            arguments={"text": "admit-fail"},
            worker_pool="general",
        )
        registry = WorkerRegistry(self.db)
        registry.initialize()
        admission = ResourceAdmission(self.db)
        admission.initialize()
        decision = mock.Mock(allowed=False, reason="RESOURCE_UNAVAILABLE", reservation_id="r1")

        def _ctx():
            return {
                "settings": mock.Mock(
                    database_path=self.db,
                    resources=mock.Mock(max_job_concurrency=2),
                ),
                "job_store": self.runtime.store,
                "job_runtime": self.runtime,
                "gateway": self.runtime.gateway,
                "registry": registry,
                "admission": admission,
                "worker_settings": WorkerSettings(
                    heartbeat_seconds=0.2,
                    lease_ttl_seconds=5.0,
                    poll_seconds=0.05,
                    pool_counts={"general": 1},
                ),
            }

        with mock.patch(
            "Data.modules.workers.loop.build_minimal_job_context", side_effect=_ctx
        ), mock.patch.object(admission, "try_reserve", return_value=decision), mock.patch.object(
            self.runtime.store,
            "schedule_retry",
            side_effect=RuntimeError("state write failed"),
        ):
            run_pool_loop(pool_id="general", handler=lambda c, j: {}, once=True, max_jobs=1)
        final = self.runtime.store.get(job.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.FAILED)
        self.assertIn("resource_admission_recovery_failed", final.error or "")


class Worker002LoopHeartbeatFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_002_heartbeat_loss_fences_handler(self) -> None:
        job = self.runtime.enqueue(
            capability_id="file.read",
            arguments={"text": "hb"},
            worker_pool="general",
        )
        saw_fence = threading.Event()
        continued = {"after": False}

        def handler(ctx, claimed):
            # Steal lease so heartbeats fail.
            with self.runtime.store.connect() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET lease_owner = ?, lease_expires_at = ?
                    WHERE job_id = ?
                    """,
                    ("thief", "2099-01-01T00:00:00+00:00", claimed.job_id),
                )
            deadline = time.time() + 5
            while time.time() < deadline:
                if ctx["job_cancel_check"]() or ctx["lease_lost"].is_set():
                    saw_fence.set()
                    break
                time.sleep(0.05)
            if not saw_fence.is_set():
                continued["after"] = True
            return {"fenced": saw_fence.is_set()}

        registry = WorkerRegistry(self.db)
        registry.initialize()
        admission = ResourceAdmission(self.db)
        admission.initialize()

        def _ctx():
            return {
                "settings": mock.Mock(
                    database_path=self.db,
                    resources=mock.Mock(max_job_concurrency=2),
                ),
                "job_store": self.runtime.store,
                "job_runtime": self.runtime,
                "gateway": self.runtime.gateway,
                "registry": registry,
                "admission": admission,
                "worker_settings": WorkerSettings(
                    heartbeat_seconds=0.15,
                    lease_ttl_seconds=2.0,
                    poll_seconds=0.05,
                    pool_counts={"general": 1},
                ),
            }

        with mock.patch(
            "Data.modules.workers.loop.build_minimal_job_context", side_effect=_ctx
        ):
            run_pool_loop(pool_id="general", handler=handler, once=True, max_jobs=1)
        self.assertTrue(saw_fence.is_set())
        self.assertFalse(continued["after"])
        _ = job


class Worker003LoopCancelFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.db"
        self.runtime = _runtime(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_003_loop_cancel_check_fail_closed(self) -> None:
        self.runtime.enqueue(
            capability_id="file.read",
            arguments={"text": "c"},
            worker_pool="general",
        )
        saw = threading.Event()

        def handler(ctx, claimed):
            broken = mock.Mock()
            broken.get.side_effect = RuntimeError("cannot read")
            # Replace store.get for cancel check path by calling helper directly.
            self.assertTrue(
                observe_job_cancel_state(
                    broken,
                    claimed.job_id,
                    worker_id=ctx["worker_id"],
                    ctx={
                        "lease_lost": ctx["lease_lost"],
                        "job_cancel_fence": ctx["job_cancel_fence"],
                    },
                )
            )
            saw.set()
            return {}

        registry = WorkerRegistry(self.db)
        registry.initialize()
        admission = ResourceAdmission(self.db)
        admission.initialize()

        def _ctx():
            return {
                "settings": mock.Mock(
                    database_path=self.db,
                    resources=mock.Mock(max_job_concurrency=2),
                ),
                "job_store": self.runtime.store,
                "job_runtime": self.runtime,
                "gateway": self.runtime.gateway,
                "registry": registry,
                "admission": admission,
                "worker_settings": WorkerSettings(
                    heartbeat_seconds=1.0,
                    lease_ttl_seconds=30.0,
                    poll_seconds=0.05,
                    pool_counts={"general": 1},
                ),
            }

        with mock.patch(
            "Data.modules.workers.loop.build_minimal_job_context", side_effect=_ctx
        ):
            run_pool_loop(pool_id="general", handler=handler, once=True, max_jobs=1)
        self.assertTrue(saw.is_set())


if __name__ == "__main__":
    unittest.main()
