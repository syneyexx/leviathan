"""Execution fabric — workers, admission, tiers, commit lane, scheduler."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from Data.modules.compute import ComputeTier, EscalationPolicy
from Data.modules.knowledge.pipeline import KnowledgeArtifact, KnowledgeCommitter
from Data.modules.schedules import ScheduleRunner, ScheduleStore, ScheduleTargetKind
from Data.modules.workers.admission import ResourceAdmission, ResourceClass
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability
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


class EscalationPolicyTests(unittest.TestCase):
    def test_tier0_ops_stay_tier0(self) -> None:
        d = EscalationPolicy().decide("hashing")
        self.assertEqual(d.tier, ComputeTier.DETERMINISTIC)
        self.assertEqual(d.reason, "tier0_owned_operation")
        sorting = EscalationPolicy().decide("sorting")
        self.assertEqual(sorting.tier, ComputeTier.DETERMINISTIC)

    def test_requires_reasoning_goes_tier3(self) -> None:
        d = EscalationPolicy().decide("synthesis", requires_reasoning=True)
        self.assertEqual(d.tier, ComputeTier.MAIN_REASONING)
        self.assertEqual(d.reason, "high_value_reasoning_required")

    def test_ambiguous_goes_tier2(self) -> None:
        d = EscalationPolicy().decide(
            "extract",
            tier0_insufficient=True,
            tier1_ambiguous=True,
        )
        self.assertEqual(d.tier, ComputeTier.SMALL_MODEL)
        self.assertEqual(d.reason, "tier1_ambiguous_try_tier2")


class WorkerRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = WorkerRegistry(Path(self.tmp.name) / "w.db")
        self.registry.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_heartbeat_reconcile_stale_dead_pid(self) -> None:
        live = WorkerRegistration(
            worker_id="w-live",
            pool_id="general",
            slot=0,
            pid=os.getpid(),
            process_start_identity=f"test:{os.getpid()}",
            started_at=utc_now(),
            last_heartbeat_at=utc_now(),
            state=WorkerInstanceState.READY,
        )
        self.registry.upsert(live)
        hb = self.registry.heartbeat(
            "w-live", state=WorkerInstanceState.BUSY, current_job_id="j1"
        )
        assert hb is not None
        self.assertEqual(hb.state, WorkerInstanceState.BUSY)
        self.assertEqual(hb.current_job_id, "j1")

        self.registry.upsert(
            WorkerRegistration(
                worker_id="w-dead",
                pool_id="general",
                slot=1,
                pid=99999999,
                process_start_identity="gone",
                state=WorkerInstanceState.READY,
                last_heartbeat_at=utc_now(),
            )
        )
        marked = self.registry.reconcile_stale(heartbeat_ttl_seconds=3600.0)
        self.assertIn("w-dead", marked)
        self.assertNotIn("w-live", marked)
        row = self.registry.get("w-dead")
        assert row is not None
        self.assertEqual(row.state, WorkerInstanceState.STALE)
        self.assertEqual(row.degraded_reason, "pid_dead")


class ResourceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "a.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gpu_exclusive_one_granted_one_denied(self) -> None:
        adm = ResourceAdmission(
            self.db,
            telemetry_reader=lambda: {
                "ram_available_mb": 8192.0,
                "vram_available_mb": 8192.0,
            },
        )
        adm.initialize()
        a = adm.try_reserve(
            job_id="j1",
            worker_id="w1",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertTrue(a.allowed)
        b = adm.try_reserve(
            job_id="j2",
            worker_id="w2",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertFalse(b.allowed)
        self.assertIn("GPU_EXCLUSIVE already held", b.reason)
        adm.release(a.reservation_id)
        c = adm.try_reserve(
            job_id="j3",
            worker_id="w3",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertTrue(c.allowed)
        adm.release(c.reservation_id)

    def test_unknown_vram_refuses_exclusive_batch(self) -> None:
        adm = ResourceAdmission(
            self.db,
            telemetry_reader=lambda: {
                "ram_available_mb": 4096.0,
                "vram_available_mb": None,
            },
        )
        adm.initialize()
        batch = adm.try_reserve(
            job_id="j-batch",
            worker_id="w4",
            resource_class=ResourceClass.BATCH,
            latency_class="batch",
        )
        self.assertFalse(batch.allowed)
        self.assertFalse(batch.vram_known)
        self.assertIn("VRAM unknown", batch.reason)

        exclusive = adm.try_reserve(
            job_id="j-ex",
            worker_id="w5",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="background",
        )
        self.assertFalse(exclusive.allowed)
        self.assertIn("VRAM unknown", exclusive.reason)

    def test_release_and_recover_expired(self) -> None:
        adm = ResourceAdmission(
            self.db,
            telemetry_reader=lambda: {
                "ram_available_mb": 8192.0,
                "vram_available_mb": 8192.0,
            },
        )
        adm.initialize()
        granted = adm.try_reserve(
            job_id="j-exp",
            worker_id="w1",
            resource_class=ResourceClass.CPU_LIGHT,
            ttl_seconds=5.0,
        )
        self.assertTrue(granted.allowed)
        assert granted.reservation_id is not None
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(
            timespec="seconds"
        )
        with adm.connect() as conn:
            conn.execute(
                "UPDATE resource_reservations SET expires_at = ? WHERE reservation_id = ?",
                (past, granted.reservation_id),
            )
        n = adm.recover_expired()
        self.assertEqual(n, 1)
        self.assertEqual(adm.list_held(), [])


class WorkerSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "s.db"
        self.settings = WorkerSettings(
            enabled=True,
            supervisor_enabled=True,
            pool_counts={p: 0 for p in POOL_CATALOG},
            restart_max_attempts=3,
            restart_window_seconds=60.0,
            restart_base_backoff=1.0,
            restart_max_backoff=10.0,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_singleton_lease_second_supervisor_fails(self) -> None:
        s1 = WorkerSupervisor(self.db, settings=self.settings)
        s1.start()
        try:
            s2 = WorkerSupervisor(self.db, settings=self.settings)
            with self.assertRaises(RuntimeError):
                s2.start()
        finally:
            s1.stop(grace_seconds=0.5)

    def test_general_pool_desired_zero_no_spawn_and_scale_noop(self) -> None:
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
            supervisor.set_desired_count("general", 0)
            self.assertEqual(supervisor._pools["general"].desired, 0)
            self.assertEqual(len(supervisor._owned), 0)
        finally:
            supervisor.stop(grace_seconds=0.5)

    def test_crash_loop_marks_degraded(self) -> None:
        supervisor = WorkerSupervisor(self.db, settings=self.settings)
        supervisor.initialize()
        for _ in range(self.settings.restart_max_attempts):
            supervisor._record_crash("general", "spawn_failed")
        state = supervisor._pools["general"]
        self.assertTrue(state.degraded)
        assert state.degraded_reason is not None
        self.assertIn("WORKER_RESTART_EXHAUSTED", state.degraded_reason)
        self.assertGreater(state.cooldown_until, time.time())


class ProcessSpawnSecurityTests(unittest.TestCase):
    def test_rejects_unknown_entrypoint(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            spawn_worker_process(
                worker_id="x",
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


class PoolMappingTests(unittest.TestCase):
    def test_coding_maps(self) -> None:
        self.assertEqual(pool_for_capability("coding.advance"), "coding")

    def test_unknown_maps_general(self) -> None:
        self.assertEqual(pool_for_capability("file.read"), "general")


class KnowledgeCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.committer = KnowledgeCommitter(Path(self.tmp.name) / "k.db")
        self.committer.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_idempotent_commit_single_receipt(self) -> None:
        art = KnowledgeArtifact.create(
            artifact_type="note",
            producer="test",
            title="t",
            content="hello",
            topics=["t"],
        )
        r1 = self.committer.commit(art, idempotency_key="idem-1")
        r2 = self.committer.commit(art, idempotency_key="idem-1")
        self.assertEqual(r1.commit_id, r2.commit_id)
        self.assertTrue(r1.success)

    def test_reject_secret_flags(self) -> None:
        art = KnowledgeArtifact.create(
            artifact_type="note",
            producer="test",
            title="secret",
            content="x",
            security_flags=["secret"],
        )
        r = self.committer.commit(art, idempotency_key="secret-1")
        self.assertTrue(r.failure)
        self.assertIn("security_flag", r.rejections)
        self.assertEqual(r.placement.get("destination"), "reject")


class ScheduleEnqueueOnlyTests(unittest.TestCase):
    def test_tick_default_does_not_call_process_next(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            store = ScheduleStore(Path(tmp.name) / "sched.db")
            store.initialize()
            store.create(
                name="noop-sched",
                target_kind=ScheduleTargetKind.JOB,
                target_ref="file.read",
                interval_seconds=60,
                target_payload={"arguments": {"path": "/tmp/x"}},
                start_after_seconds=0,
            )
            jobs = mock.Mock()
            jobs.enqueue.return_value = mock.Mock(
                job_id="j1", state=mock.Mock(value="QUEUED")
            )
            runner = ScheduleRunner(store, jobs=jobs)
            results = runner.tick()  # default execute=False
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["ok"])
            self.assertFalse(results[0].get("executed_inline"))
            jobs.enqueue.assert_called_once()
            jobs.process_next.assert_not_called()
        finally:
            tmp.cleanup()


class ArchitectureImportGuardTests(unittest.TestCase):
    def test_worker_loop_source_avoids_backend_main(self) -> None:
        path = Path(__file__).resolve().parents[2] / "modules" / "workers" / "loop.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(
                    node.module == "Data.backend.main"
                    or node.module.startswith("Data.backend.main."),
                    f"forbidden import {node.module}",
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "Data.backend.main")


if __name__ == "__main__":
    unittest.main()
