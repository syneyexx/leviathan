"""Execution fabric — workers, admission, tiers, commit lane, scheduler."""

from __future__ import annotations

import ast
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.compute import ComputeTier, EscalationPolicy
from Data.modules.knowledge.pipeline import KnowledgeArtifact, KnowledgeCommitter
from Data.modules.workers.admission import ResourceAdmission, ResourceClass
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability
from Data.modules.workers.process import ALLOWED_ENTRYPOINT_PREFIX, spawn_worker_process
from Data.modules.workers.protocol import WorkerInstanceState, WorkerRegistration
from Data.modules.workers.registry import WorkerRegistry
from Data.modules.workers.settings import WorkerSettings
from Data.modules.workers.supervisor import WorkerSupervisor


class EscalationPolicyTests(unittest.TestCase):
    def test_tier0_hashing(self) -> None:
        d = EscalationPolicy().decide("hashing")
        self.assertEqual(d.tier, ComputeTier.DETERMINISTIC)

    def test_reasoning_escalates(self) -> None:
        d = EscalationPolicy().decide("synthesis", requires_reasoning=True)
        self.assertEqual(d.tier, ComputeTier.MAIN_REASONING)

    def test_ambiguous_uses_small_model(self) -> None:
        d = EscalationPolicy().decide(
            "extract",
            tier0_insufficient=True,
            tier1_ambiguous=True,
        )
        self.assertEqual(d.tier, ComputeTier.SMALL_MODEL)


class WorkerRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = WorkerRegistry(Path(self.tmp.name) / "w.db")
        self.registry.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_heartbeat(self) -> None:
        reg = WorkerRegistration(
            worker_id="w1",
            pool_id="general",
            slot=0,
            pid=1,
            process_start_identity="test:1",
            state=WorkerInstanceState.READY,
            last_heartbeat_at="2000-01-01T00:00:00+00:00",
        )
        self.registry.upsert(reg)
        hb = self.registry.heartbeat("w1", state=WorkerInstanceState.BUSY, current_job_id="j1")
        assert hb is not None
        self.assertEqual(hb.state, WorkerInstanceState.BUSY)
        self.assertEqual(hb.current_job_id, "j1")

    def test_reconcile_stale_dead_pid(self) -> None:
        self.registry.upsert(
            WorkerRegistration(
                worker_id="dead",
                pool_id="general",
                slot=0,
                pid=99999999,
                process_start_identity="gone",
                state=WorkerInstanceState.READY,
                last_heartbeat_at="2000-01-01T00:00:00+00:00",
            )
        )
        marked = self.registry.reconcile_stale(heartbeat_ttl_seconds=1.0)
        self.assertIn("dead", marked)
        row = self.registry.get("dead")
        assert row is not None
        self.assertEqual(row.state, WorkerInstanceState.STALE)


class ResourceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.adm = ResourceAdmission(
            Path(self.tmp.name) / "a.db",
            telemetry_reader=lambda: {"ram_available_mb": 4096.0, "vram_available_mb": None},
        )
        self.adm.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gpu_exclusive_single(self) -> None:
        a = self.adm.try_reserve(
            job_id="j1",
            worker_id="w1",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertTrue(a.allowed)
        b = self.adm.try_reserve(
            job_id="j2",
            worker_id="w2",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertFalse(b.allowed)
        self.adm.release(a.reservation_id)
        c = self.adm.try_reserve(
            job_id="j3",
            worker_id="w3",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="interactive",
        )
        self.assertTrue(c.allowed)

    def test_unknown_vram_refuses_batch_exclusive(self) -> None:
        d = self.adm.try_reserve(
            job_id="j4",
            worker_id="w4",
            resource_class=ResourceClass.GPU_EXCLUSIVE,
            latency_class="batch",
        )
        self.assertFalse(d.allowed)
        self.assertFalse(d.vram_known)


class SupervisorLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "s.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_second_supervisor_denied(self) -> None:
        settings = WorkerSettings(enabled=True, supervisor_enabled=True, pool_counts={p: 0 for p in POOL_CATALOG})
        s1 = WorkerSupervisor(self.db, settings=settings)
        s1.start()
        s2 = WorkerSupervisor(self.db, settings=settings)
        with self.assertRaises(RuntimeError):
            s2.start()
        s1.stop(grace_seconds=1.0)


class ProcessSpawnSecurityTests(unittest.TestCase):
    def test_rejects_unknown_entrypoint(self) -> None:
        with self.assertRaises(ValueError):
            spawn_worker_process(
                worker_id="x",
                pool_id="general",
                slot=0,
                entrypoint="os.system",
            )
        self.assertTrue(ALLOWED_ENTRYPOINT_PREFIX.startswith("Data.modules.workers"))


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

    def test_idempotent_commit(self) -> None:
        art = KnowledgeArtifact.create(
            artifact_type="note",
            producer="test",
            title="t",
            content="hello",
        )
        r1 = self.committer.commit(art, idempotency_key="idem-1")
        r2 = self.committer.commit(art, idempotency_key="idem-1")
        self.assertEqual(r1.commit_id, r2.commit_id)
        self.assertTrue(r1.success)

    def test_reject_secrets(self) -> None:
        art = KnowledgeArtifact.create(
            artifact_type="note",
            producer="test",
            title="secret",
            content="x",
        )
        art.security_flags = ["secret"]
        r = self.committer.commit(art)
        self.assertTrue(r.failure)
        self.assertIn("security_flag", r.rejections)


class ScheduleEnqueueOnlyTests(unittest.TestCase):
    def test_tick_default_no_inline_execute(self) -> None:
        from Data.modules.schedules.runner import ScheduleRunner
        from Data.modules.schedules.store import ScheduleStore

        tmp = tempfile.TemporaryDirectory()
        try:
            store = ScheduleStore(Path(tmp.name) / "sched.db")
            store.initialize()
            jobs = mock.Mock()
            jobs.enqueue.return_value = mock.Mock(job_id="j1", state=mock.Mock(value="QUEUED"))
            runner = ScheduleRunner(store, jobs=jobs)
            # no due schedules → process_next never called
            runner.tick()
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
                    node.module == "Data.backend.main" or node.module.startswith("Data.backend.main."),
                    f"forbidden import {node.module}",
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "Data.backend.main")


if __name__ == "__main__":
    unittest.main()
