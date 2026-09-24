from __future__ import annotations

import inspect
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.compute.tiers import ComputeTier, EscalationPolicy
from Data.modules.knowledge.pipeline.artifact import KnowledgeArtifact
from Data.modules.knowledge.pipeline.committer import KnowledgeCommitter
from Data.modules.schedules import ScheduleRunner, ScheduleStore, ScheduleTargetKind
from Data.modules.workers.admission import ResourceAdmission, ResourceClass
from Data.modules.workers.pools import POOL_CATALOG
from Data.modules.workers.process import (
    ALLOWED_ENTRYPOINT_PREFIX,
    OwnedProcess,
    spawn_worker_process,
    verify_owned,
)
from Data.modules.workers.protocol import WorkerInstanceState, WorkerRegistration
from Data.modules.workers.registry import WorkerRegistry, utc_now
from Data.modules.workers.settings import WorkerSettings
from Data.modules.workers.supervisor import WorkerSupervisor
from Data.modules.workers import loop as workers_loop


class WorkerRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = WorkerRegistry(Path(self.tmp.name) / "w.db")
        self.registry.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_heartbeat_reconcile_stale_dead_pid(self) -> None:
        reg = WorkerRegistration(
            worker_id="w-live",
            pool_id="general",
            slot=0,
            pid=os.getpid(),
            process_start_identity=f"test:{os.getpid()}",
            started_at=utc_now(),
            last_heartbeat_at=utc_now(),
            state=WorkerInstanceState.READY,
        )
        self.registry.upsert(reg)
        hb = self.registry.heartbeat("w-live", state=WorkerInstanceState.BUSY, current_job_id="j1")
        assert hb is not None
        self.assertEqual(hb.state, WorkerInstanceState.BUSY)
        self.assertEqual(hb.current_job_id, "j1")

        dead = WorkerRegistration(
            worker_id="w-dead",
            pool_id="general",
            slot=1,
            pid=2**22,  # almost certainly not a live PID
            process_start_identity="test:dead",
            started_at=utc_now(),
            last_heartbeat_at=utc_now(),
            state=WorkerInstanceState.READY,
        )
        self.registry.upsert(dead)
        marked = self.registry.reconcile_stale(heartbeat_ttl_seconds=3600.0)
        self.assertIn("w-dead", marked)
        self.assertNotIn("w-live", marked)
        stale = self.registry.get("w-dead")
        assert stale is not None
        self.assertEqual(stale.state, WorkerInstanceState.STALE)
        self.assertEqual(stale.degraded_reason, "pid_dead")
        still = self.registry.get("w-live")
        assert still is not None
        self.assertEqual(still.state, WorkerInstanceState.BUSY)


class ResourceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "r.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gpu_exclusive_one_granted_one_denied(self) -> None:
        admission = ResourceAdmission(
            self.db,
            telemetry_reader=lambda: {"ram_available_mb": 8192.0, "vram_available_mb": 8192.0},
        )
        admission.initialize()
        first = admission.try_reserve(
            job_id="j1",
            worker_id="w1",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertTrue(first.allowed)
        self.assertIsNotNone(first.reservation_id)

        second = admission.try_reserve(
            job_id="j2",
            worker_id="w2",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertFalse(second.allowed)
        self.assertIn("GPU_EXCLUSIVE already held", second.reason)

        admission.release(first.reservation_id)
        third = admission.try_reserve(
            job_id="j3",
            worker_id="w3",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertTrue(third.allowed)
        admission.release(third.reservation_id)

    def test_unknown_vram_refuses_exclusive_batch(self) -> None:
        admission = ResourceAdmission(
            self.db,
            telemetry_reader=lambda: {"ram_available_mb": 4096.0, "vram_available_mb": None},
        )
        admission.initialize()
        denied = admission.try_reserve(
            job_id="batch-1",
            worker_id="w1",
            resource_class=ResourceClass.BATCH,
            latency_class="batch",
        )
        self.assertFalse(denied.allowed)
        self.assertIn("VRAM unknown", denied.reason)
        self.assertFalse(denied.vram_known)

        exclusive = admission.try_reserve(
            job_id="ex-1",
            worker_id="w1",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="background",
        )
        self.assertFalse(exclusive.allowed)
        self.assertIn("VRAM unknown", exclusive.reason)

    def test_release_and_recover_expired(self) -> None:
        admission = ResourceAdmission(
            self.db,
            telemetry_reader=lambda: {"ram_available_mb": 8192.0, "vram_available_mb": 8192.0},
        )
        admission.initialize()
        granted = admission.try_reserve(
            job_id="j-exp",
            worker_id="w1",
            resource_class=ResourceClass.CPU_LIGHT,
            ttl_seconds=5.0,
        )
        self.assertTrue(granted.allowed)
        assert granted.reservation_id is not None

        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(timespec="seconds")
        with admission.connect() as conn:
            conn.execute(
                "UPDATE resource_reservations SET expires_at = ? WHERE reservation_id = ?",
                (past, granted.reservation_id),
            )
        n = admission.recover_expired()
        self.assertEqual(n, 1)
        self.assertEqual(admission.list_held(), [])


class WorkerSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "sup.db"
        # desired=0 everywhere — no real spawn storm
        zero_counts = {pid: 0 for pid in POOL_CATALOG}
        self.settings = WorkerSettings(
            pool_counts=zero_counts,
            restart_max_attempts=3,
            restart_window_seconds=60.0,
            restart_base_backoff=1.0,
            restart_max_backoff=10.0,
            supervisor_lease_ttl_seconds=30.0,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_singleton_lease_second_supervisor_fails(self) -> None:
        first = WorkerSupervisor(self.db, settings=self.settings, log_dir=Path(self.tmp.name) / "logs")
        first.initialize()
        self.assertTrue(first.acquire())

        second = WorkerSupervisor(self.db, settings=self.settings, log_dir=Path(self.tmp.name) / "logs2")
        second.initialize()
        self.assertFalse(second.acquire())

        first.registry.release_supervisor_lease(holder_id=first.holder_id)

    def test_spawn_general_desired_zero_and_scale_noop(self) -> None:
        supervisor = WorkerSupervisor(
            self.db,
            settings=self.settings,
            log_dir=Path(self.tmp.name) / "logs",
        )
        supervisor.start()
        try:
            self.assertEqual(supervisor._pools["general"].desired, 0)
            supervisor.reconcile_pools()
            self.assertEqual(len(supervisor._owned), 0)
            # Scale 0 → 0 is a no-op
            supervisor.set_desired_count("general", 0)
            self.assertEqual(supervisor._pools["general"].desired, 0)
            self.assertEqual(len(supervisor._owned), 0)
        finally:
            supervisor.stop(grace_seconds=0.5)

    def test_crash_loop_marks_degraded(self) -> None:
        supervisor = WorkerSupervisor(
            self.db,
            settings=self.settings,
            log_dir=Path(self.tmp.name) / "logs",
        )
        supervisor.initialize()
        for _ in range(self.settings.restart_max_attempts):
            supervisor._record_crash("general", "spawn_failed")
        state = supervisor._pools["general"]
        self.assertTrue(state.degraded)
        self.assertIsNotNone(state.degraded_reason)
        assert state.degraded_reason is not None
        self.assertIn("WORKER_RESTART_EXHAUSTED", state.degraded_reason)
        self.assertGreater(state.cooldown_until, time.time())


class ProcessGuardTests(unittest.TestCase):
    def test_allowed_entrypoint_prefix_rejects_bad(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            spawn_worker_process(
                worker_id="bad",
                pool_id="general",
                slot=0,
                entrypoint="os.system",
            )
        self.assertIn("Refusing unknown worker entrypoint", str(ctx.exception))
        self.assertTrue(ALLOWED_ENTRYPOINT_PREFIX.startswith("Data.modules.workers.entrypoints."))

    def test_verify_owned_false_when_popen_exited(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(0)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=5)
        owned = OwnedProcess(
            worker_id="exited",
            pool_id="general",
            slot=0,
            pid=int(proc.pid),
            process_start_identity=f"pid:{proc.pid}:test",
            popen=proc,
        )
        self.assertFalse(verify_owned(owned))


class EscalationPolicyTests(unittest.TestCase):
    def test_tier0_ops_stay_tier0(self) -> None:
        policy = EscalationPolicy()
        decision = policy.decide("hashing")
        self.assertEqual(decision.tier, ComputeTier.DETERMINISTIC)
        self.assertEqual(decision.reason, "tier0_owned_operation")

        sorting = policy.decide("sorting")
        self.assertEqual(sorting.tier, ComputeTier.DETERMINISTIC)

    def test_requires_reasoning_goes_tier3(self) -> None:
        policy = EscalationPolicy()
        decision = policy.decide("open_question", requires_reasoning=True)
        self.assertEqual(decision.tier, ComputeTier.MAIN_REASONING)
        self.assertEqual(decision.reason, "high_value_reasoning_required")

    def test_ambiguous_goes_tier2(self) -> None:
        policy = EscalationPolicy()
        decision = policy.decide(
            "classify_snippet",
            tier0_insufficient=True,
            tier1_ambiguous=True,
        )
        self.assertEqual(decision.tier, ComputeTier.SMALL_MODEL)
        self.assertEqual(decision.reason, "tier1_ambiguous_try_tier2")


class KnowledgeCommitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.committer = KnowledgeCommitter(Path(self.tmp.name) / "k.db")
        self.committer.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_idempotent_commit_single_receipt(self) -> None:
        artifact = KnowledgeArtifact.create(
            artifact_type="note",
            producer="test",
            title="Hello",
            content="body",
            topics=["t"],
        )
        first = self.committer.commit(artifact, idempotency_key="commit-key-1")
        second = self.committer.commit(artifact, idempotency_key="commit-key-1")
        self.assertEqual(first.commit_id, second.commit_id)
        self.assertTrue(first.success)

    def test_reject_secret_flags(self) -> None:
        artifact = KnowledgeArtifact.create(
            artifact_type="note",
            producer="test",
            title="Secret",
            content="token=abc",
            security_flags=["secret"],
        )
        receipt = self.committer.commit(artifact, idempotency_key="secret-1")
        self.assertTrue(receipt.failure)
        self.assertIn("security_flag", receipt.rejections)
        self.assertEqual(receipt.placement.get("destination"), "reject")


class ScheduleRunnerEnqueueOnlyTests(unittest.TestCase):
    def test_tick_default_does_not_call_process_next(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "s.db"
            store = ScheduleStore(db)
            store.initialize()
            store.create(
                name="noop-sched",
                target_kind=ScheduleTargetKind.JOB,
                target_ref="file.read",
                interval_seconds=60,
                target_payload={"arguments": {"path": "/tmp/x"}},
                start_after_seconds=0,
            )
            jobs = MagicMock()
            enqueued = MagicMock()
            enqueued.job_id = "job-1"
            enqueued.state = MagicMock(value="QUEUED")
            jobs.enqueue.return_value = enqueued
            runner = ScheduleRunner(store, jobs=jobs)
            results = runner.tick()  # default execute=False
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["ok"])
            self.assertFalse(results[0].get("executed_inline"))
            jobs.enqueue.assert_called_once()
            jobs.process_next.assert_not_called()
        finally:
            tmp.cleanup()


class ArchitectureGuardTests(unittest.TestCase):
    def test_build_minimal_job_context_does_not_import_backend_main(self) -> None:
        source = inspect.getsource(workers_loop.build_minimal_job_context)
        self.assertNotIn("Data.backend.main", source)
        self.assertNotIn("backend.main", source)
        module_source = Path(inspect.getfile(workers_loop)).read_text(encoding="utf-8")
        # Module docstring + body must not pull FastAPI app factory.
        self.assertNotIn("from Data.backend.main", module_source)
        self.assertNotIn("import Data.backend.main", module_source)


if __name__ == "__main__":
    unittest.main()
