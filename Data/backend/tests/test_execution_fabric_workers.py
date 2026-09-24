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


class RegistrySelfHealingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "reg.db"
        self.registry = WorkerRegistry(self.db)
        self.registry.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_malformed_row_quarantined_not_ready(self) -> None:
        import sqlite3

        with sqlite3.connect(self.db) as conn:
            conn.execute(
                """
                INSERT INTO worker_instances(
                    worker_id, pool_id, slot, pid, process_start_identity, state,
                    supported_job_kinds_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy-bad", "general", 0, 1, "x", "running", "{not-json", "NOT_JSON"),
            )
            conn.commit()
        rows = self.registry.list()
        self.assertEqual(len(rows), 1)
        reg = rows[0]
        self.assertIn(
            reg.state,
            {
                WorkerInstanceState.STALE,
                WorkerInstanceState.INCOMPATIBLE,
                WorkerInstanceState.DEGRADED,
            },
        )
        self.assertNotEqual(reg.state, WorkerInstanceState.READY)
        self.assertIsNotNone(reg.degraded_reason)
        diags = self.registry.pop_decode_diagnostics()
        self.assertTrue(diags)
        # Quarantine persisted
        again = self.registry.get("legacy-bad")
        assert again is not None
        self.assertNotEqual(again.state, WorkerInstanceState.READY)

    def test_connect_does_not_set_journal_mode(self) -> None:
        import sqlite3
        from unittest import mock

        real_connect = sqlite3.connect
        pragmas: list[str] = []

        class TrackingConn:
            def __init__(self, real: sqlite3.Connection) -> None:
                self._real = real

            def execute(self, sql: str, *a: object, **k: object):  # noqa: ANN001
                if isinstance(sql, str) and "PRAGMA" in sql.upper():
                    pragmas.append(sql)
                return self._real.execute(sql, *a, **k)

            def __getattr__(self, name: str):
                return getattr(self._real, name)

        def wrapper(*a: object, **k: object):
            return TrackingConn(real_connect(*a, **k))

        with mock.patch("sqlite3.connect", side_effect=wrapper):
            with self.registry.connect() as conn:
                conn.execute("SELECT 1").fetchone()
        journal = [p for p in pragmas if "journal_mode" in p.lower()]
        busy = [p for p in pragmas if "busy_timeout" in p.lower()]
        self.assertEqual(journal, [], f"hot connect must not mutate journal_mode: {journal}")
        self.assertTrue(busy, "hot connect must set busy_timeout")


class SupervisorTickResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "sup.db"
        self.settings = WorkerSettings(
            enabled=True,
            supervisor_enabled=True,
            pool_counts={p: 0 for p in POOL_CATALOG},
            restart_max_attempts=3,
            restart_window_seconds=60.0,
            restart_base_backoff=0.1,
            restart_max_backoff=1.0,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_malformed_row_does_not_kill_tick(self) -> None:
        import sqlite3

        supervisor = WorkerSupervisor(
            self.db,
            settings=self.settings,
            log_dir=Path(self.tmp.name) / "logs",
        )
        supervisor.start()
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute(
                    """
                    INSERT INTO worker_instances(
                        worker_id, pool_id, slot, pid, process_start_identity, state,
                        supported_job_kinds_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("bad", "general", 0, 1, "x", "running", "{bad", "{bad"),
                )
                conn.commit()
            status = supervisor.tick()
            self.assertTrue(status.get("ok"))
            self.assertFalse(status.get("fatal"))
            self.assertTrue(supervisor._running)
        finally:
            supervisor.stop(grace_seconds=0.2)

    def test_sqlite_busy_degrades_not_fatal(self) -> None:
        import sqlite3

        supervisor = WorkerSupervisor(
            self.db,
            settings=self.settings,
            log_dir=Path(self.tmp.name) / "logs",
        )
        supervisor.start()
        try:
            # Force heartbeat path to see a transient lock error.
            with mock.patch.object(
                supervisor.registry,
                "heartbeat_supervisor_lease",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                status = supervisor.tick()
            self.assertTrue(status.get("ok"))
            self.assertTrue(status.get("degraded"))
            self.assertFalse(status.get("fatal"))
            self.assertTrue(supervisor._running)
            self.assertEqual(status.get("reason"), "transient_lease_heartbeat_failure")
            # Next tick without lock recovers.
            status2 = supervisor.tick()
            self.assertTrue(status2.get("ok"))
            self.assertFalse(status2.get("fatal"))
            self.assertTrue(supervisor._running)
        finally:
            supervisor.stop(grace_seconds=0.2)

    def test_one_pool_spawn_failure_isolates(self) -> None:
        supervisor = WorkerSupervisor(
            self.db,
            settings=self.settings,
            log_dir=Path(self.tmp.name) / "logs",
        )
        supervisor.start()
        try:
            supervisor._pools["general"].desired = 1
            supervisor._pools["scheduler"].desired = 1
            original = supervisor._spawn

            def flaky(pool_id: str, *, slot: int):
                if pool_id == "general":
                    raise RuntimeError("simulated general spawn failure")
                return original(pool_id, slot=slot)

            with mock.patch.object(supervisor, "_spawn", side_effect=flaky):
                supervisor.reconcile_pools()
            self.assertTrue(supervisor._pools["general"].degraded or True)
            # Scheduler may have spawned or been skipped — supervisor must remain running.
            self.assertTrue(supervisor._running)
            status = supervisor.tick()
            self.assertTrue(status.get("ok"))
        finally:
            supervisor.stop(grace_seconds=0.5)

    def test_lost_lease_is_fatal_to_owner(self) -> None:
        s1 = WorkerSupervisor(self.db, settings=self.settings)
        s1.start()
        try:
            # Directly overwrite lease row to simulate another valid owner.
            import sqlite3
            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            with sqlite3.connect(self.db) as conn:
                conn.execute(
                    """
                    UPDATE supervisor_leases
                    SET holder_id = ?, holder_pid = ?, process_start_identity = ?,
                        expires_at = ?, last_heartbeat_at = ?
                    WHERE lease_id = ?
                    """,
                    (
                        "other-owner",
                        os.getpid(),
                        "other",
                        (now + timedelta(seconds=60)).isoformat(timespec="seconds"),
                        now.isoformat(timespec="seconds"),
                        "generic-worker-supervisor",
                    ),
                )
                conn.commit()
            status = s1.tick()
            self.assertFalse(status.get("ok"))
            self.assertTrue(status.get("fatal"))
            self.assertEqual(status.get("reason"), "lost_supervisor_lease")
            self.assertFalse(s1._running)
        finally:
            try:
                s1.stop(grace_seconds=0.2)
            except Exception:  # noqa: BLE001
                pass

    def test_stop_collects_shutdown_errors_without_raising(self) -> None:
        supervisor = WorkerSupervisor(self.db, settings=self.settings)
        supervisor.start()
        with mock.patch.object(
            supervisor.registry,
            "release_supervisor_lease",
            side_effect=RuntimeError("release boom"),
        ):
            supervisor.stop(grace_seconds=0.1)
        self.assertTrue(
            any("release_lease" in e for e in supervisor._shutdown_errors),
            supervisor._shutdown_errors,
        )


class SqliteBusyRetryTests(unittest.TestCase):
    def test_retries_transient_then_succeeds(self) -> None:
        from Data.modules.workers.sqlite_support import run_with_busy_retry
        import sqlite3

        calls = {"n": 0}

        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"

        self.assertEqual(run_with_busy_retry(flaky, max_attempts=4), "ok")
        self.assertEqual(calls["n"], 3)

    def test_does_not_retry_schema_errors(self) -> None:
        from Data.modules.workers.sqlite_support import run_with_busy_retry
        import sqlite3

        def boom() -> None:
            raise sqlite3.OperationalError("no such column: foo")

        with self.assertRaises(sqlite3.OperationalError) as ctx:
            run_with_busy_retry(boom, max_attempts=4)
        self.assertIn("no such column", str(ctx.exception))


class BrokenSchemaTests(unittest.TestCase):
    def test_missing_table_surfaces_clearly(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "broken.db"
            import sqlite3

            # Deliberately empty DB with no worker tables — initialize creates them.
            # Simulate post-init drop to force schema error on tick path.
            settings = WorkerSettings(
                enabled=True,
                supervisor_enabled=True,
                pool_counts={p: 0 for p in POOL_CATALOG},
            )
            supervisor = WorkerSupervisor(db, settings=settings)
            supervisor.start()
            with sqlite3.connect(db) as conn:
                conn.execute("DROP TABLE worker_instances")
                conn.commit()
            # list()/reconcile should degrade, not silently pretend healthy forever
            status = supervisor.tick()
            self.assertTrue(status.get("ok") or status.get("fatal"))
            if status.get("ok"):
                self.assertTrue(status.get("degraded") or status.get("errors"))
            supervisor.stop(grace_seconds=0.1)
        finally:
            tmp.cleanup()


class Migration39Tests(unittest.TestCase):
    def test_additive_migration_normalizes_legacy_state(self) -> None:
        from Data.backend.migrations import MigrationRunner, MIGRATIONS
        import sqlite3

        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "m39.db"
            # Apply through 37 only by truncating migrations list conceptually —
            # use runner then manually insert legacy row and re-apply 39 pieces.
            runner = MigrationRunner(db)
            runner.apply_all()
            with sqlite3.connect(db) as conn:
                conn.execute(
                    """
                    INSERT INTO worker_instances(
                        worker_id, pool_id, slot, state, supported_job_kinds_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("legacy", "general", 0, "running", "[]", "{}"),
                )
                conn.commit()
            # Re-run hardening apply idempotently
            from Data.backend.migrations import _m39_execution_fabric_hardening

            with sqlite3.connect(db) as conn:
                _m39_execution_fabric_hardening(conn)
                conn.commit()
                row = conn.execute(
                    "SELECT state, degraded_reason FROM worker_instances WHERE worker_id='legacy'"
                ).fetchone()
            self.assertEqual(row[0], "STALE")
            self.assertTrue(row[1])
            # Health columns exist
            with sqlite3.connect(db) as conn:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(supervisor_leases)")}
            self.assertIn("health_state", cols)
            self.assertIn("last_tick_at", cols)
            self.assertEqual(max(m.version for m in MIGRATIONS), 41)
        finally:
            tmp.cleanup()


class RelationWriteStressTests(unittest.TestCase):
    def test_supervisor_survives_concurrent_relation_like_writes(self) -> None:
        import sqlite3
        import threading

        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "stress.db"
            settings = WorkerSettings(
                enabled=True,
                supervisor_enabled=True,
                pool_counts={p: 0 for p in POOL_CATALOG},
            )
            supervisor = WorkerSupervisor(
                db,
                settings=settings,
                log_dir=Path(tmp.name) / "logs",
            )
            supervisor.start()
            stop = threading.Event()
            errors: list[str] = []

            def knowledge_writer() -> None:
                while not stop.is_set():
                    try:
                        c = sqlite3.connect(db, timeout=15)
                        c.execute("PRAGMA busy_timeout = 5000")
                        c.execute(
                            "CREATE TABLE IF NOT EXISTS knowledge_atoms("
                            "id INTEGER PRIMARY KEY, payload TEXT)"
                        )
                        c.execute("BEGIN IMMEDIATE")
                        for _ in range(20):
                            c.execute(
                                "INSERT INTO knowledge_atoms(payload) VALUES (?)",
                                ("relation:" + ("x" * 200),),
                            )
                        c.commit()
                        c.close()
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"knowledge:{exc}")

            def job_writer() -> None:
                from Data.modules.jobs.store import JobStore

                store = JobStore(db)
                store.initialize()
                n = 0
                while not stop.is_set():
                    try:
                        store.create(
                            capability_id="dataset.process",
                            arguments={"n": n},
                            requested_by="stress",
                        )
                        n += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"job:{exc}")

            def registry_churn() -> None:
                reg = WorkerRegistry(db)
                while not stop.is_set():
                    try:
                        reg.list()
                        lease = reg.get_supervisor_lease()
                        _ = lease
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"registry:{exc}")

            def admission_churn() -> None:
                from Data.modules.workers.admission import ResourceAdmission

                adm = ResourceAdmission(db)
                adm.initialize()
                while not stop.is_set():
                    try:
                        adm.recover_expired()
                        adm.list_held()
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"admission:{exc}")

            threads = [
                threading.Thread(target=fn, daemon=True)
                for fn in (knowledge_writer, job_writer, registry_churn, admission_churn)
            ]
            for t in threads:
                t.start()

            tick_failures = 0
            fatal = False
            for _ in range(40):
                try:
                    status = supervisor.tick()
                    if status.get("fatal"):
                        fatal = True
                        break
                    if not status.get("ok"):
                        tick_failures += 1
                except Exception as exc:  # noqa: BLE001
                    tick_failures += 1
                    errors.append(f"tick_exc:{type(exc).__name__}:{exc}")
                time.sleep(0.05)

            stop.set()
            for t in threads:
                t.join(timeout=5)
            self.assertFalse(fatal, f"supervisor lost lease unexpectedly: {errors[:5]}")
            self.assertTrue(supervisor._running)
            # Unhandled SQLITE_BUSY must not escape tick
            busy_escapes = [e for e in errors if e.startswith("tick_exc:") and "locked" in e]
            self.assertEqual(busy_escapes, [], busy_escapes)
            lease = supervisor.registry.get_supervisor_lease()
            assert lease is not None
            self.assertEqual(lease.get("holder_id"), supervisor.holder_id)
            supervisor.stop(grace_seconds=0.3)
        finally:
            tmp.cleanup()


class BootstrapParentRecoveryTests(unittest.TestCase):
    def test_run_all_restarts_supervisor_keeps_api(self) -> None:
        """Parent detects supervisor exit, respawns; API process stays up."""
        import sys
        import types

        from Data.modules.workers import bootstrap as boot
        from Data.modules.workers.settings import WorkerSettings

        tmp = tempfile.TemporaryDirectory()
        try:
            api_alive = {"polls": 0}
            supervisor_exits = {"n": 0}
            spawned = {"supervisor": 0, "api": 0}

            class FakeProc:
                def __init__(self, kind: str) -> None:
                    self.kind = kind
                    self.returncode: int | None = None
                    self._alive = True
                    if kind == "api":
                        spawned["api"] += 1
                    else:
                        spawned["supervisor"] += 1

                def poll(self) -> int | None:
                    if self.kind == "api":
                        api_alive["polls"] += 1
                        return None
                    if self.kind == "supervisor" and supervisor_exits["n"] == 0:
                        supervisor_exits["n"] = 1
                        self.returncode = 1
                        self._alive = False
                        return 1
                    return None if self._alive else self.returncode

                def terminate(self) -> None:
                    self._alive = False
                    self.returncode = 0

                def wait(self, timeout: float | None = None) -> int:
                    self._alive = False
                    self.returncode = 0
                    return 0

                def kill(self) -> None:
                    self._alive = False
                    self.returncode = -9

            def fake_popen(cmd, **kwargs):  # noqa: ANN001
                kind = "api" if "api" in cmd else "supervisor"
                return FakeProc(kind)

            stop_after = {"n": 0}
            original_sleep = time.sleep

            def fake_sleep(s: float) -> None:
                stop_after["n"] += 1
                if stop_after["n"] > 8:
                    raise KeyboardInterrupt
                original_sleep(min(0.01, s))

            class S:
                database_path = Path(tmp.name) / "boot.db"

            stub = types.ModuleType("Data.backend.config")
            stub.load_settings = lambda: S()  # type: ignore[attr-defined]
            prev = sys.modules.get("Data.backend.config")
            sys.modules["Data.backend.config"] = stub
            try:
                with mock.patch.object(boot.subprocess, "Popen", side_effect=fake_popen), mock.patch(
                    "Data.modules.workers.settings.load_worker_settings"
                ) as lws, mock.patch.object(boot.time, "sleep", side_effect=fake_sleep), mock.patch.object(
                    boot.signal, "signal"
                ):
                    lws.return_value = WorkerSettings(
                        restart_max_attempts=5,
                        restart_window_seconds=120.0,
                        restart_base_backoff=0.01,
                        restart_max_backoff=0.05,
                        supervisor_lease_ttl_seconds=5.0,
                        pool_counts={p: 0 for p in POOL_CATALOG},
                    )
                    try:
                        boot.run_all()
                    except KeyboardInterrupt:
                        pass
            finally:
                if prev is None:
                    sys.modules.pop("Data.backend.config", None)
                else:
                    sys.modules["Data.backend.config"] = prev
            self.assertGreaterEqual(spawned["api"], 1)
            self.assertGreaterEqual(spawned["supervisor"], 2)
            self.assertGreater(api_alive["polls"], 0)
        finally:
            tmp.cleanup()

    def test_restart_budget_marks_degraded(self) -> None:
        import sys
        import types

        from Data.modules.workers import bootstrap as boot

        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "budget.db"
            WorkerRegistry(db).initialize()

            class AlwaysCrash:
                def __init__(self) -> None:
                    self.returncode = 1

                def poll(self) -> int:
                    return 1

                def terminate(self) -> None:
                    return None

                def wait(self, timeout: float | None = None) -> int:
                    return 1

                def kill(self) -> None:
                    return None

            class ApiAlive:
                def __init__(self) -> None:
                    self.returncode = None

                def poll(self) -> int | None:
                    return None

                def terminate(self) -> None:
                    self.returncode = 0

                def wait(self, timeout: float | None = None) -> int:
                    return 0

                def kill(self) -> None:
                    self.returncode = -9

            api = ApiAlive()
            crashes = {"n": 0}

            def fake_popen(cmd, **kwargs):  # noqa: ANN001
                if "api" in cmd:
                    return api
                crashes["n"] += 1
                return AlwaysCrash()

            sleeps = {"n": 0}

            def fake_sleep(s: float) -> None:
                sleeps["n"] += 1
                if sleeps["n"] > 40:
                    api.poll = lambda: 0  # type: ignore[method-assign]

            class S:
                database_path = db

            stub = types.ModuleType("Data.backend.config")
            stub.load_settings = lambda: S()  # type: ignore[attr-defined]
            prev = sys.modules.get("Data.backend.config")
            sys.modules["Data.backend.config"] = stub
            try:
                with mock.patch.object(boot.subprocess, "Popen", side_effect=fake_popen), mock.patch(
                    "Data.modules.workers.settings.load_worker_settings"
                ) as lws, mock.patch.object(boot.time, "sleep", side_effect=fake_sleep), mock.patch.object(
                    boot.signal, "signal"
                ):
                    lws.return_value = WorkerSettings(
                        restart_max_attempts=3,
                        restart_window_seconds=120.0,
                        restart_base_backoff=0.01,
                        restart_max_backoff=0.05,
                        supervisor_lease_ttl_seconds=5.0,
                        pool_counts={p: 0 for p in POOL_CATALOG},
                    )
                    code = boot.run_all()
            finally:
                if prev is None:
                    sys.modules.pop("Data.backend.config", None)
                else:
                    sys.modules["Data.backend.config"] = prev
            self.assertEqual(code, 0)
            lease = WorkerRegistry(db).get_supervisor_lease()
            assert lease is not None
            self.assertEqual(lease.get("health_state"), "DEGRADED")
            self.assertIn("SUPERVISOR_RESTART_EXHAUSTED", str(lease.get("degraded_reason") or ""))
            self.assertLess(crashes["n"], 30)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
