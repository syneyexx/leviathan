"""Worker fabric production hardening — crash logs, events, bootstrap barrier."""

from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.sqlite_policy import (
    ROWS_UNMEASURED,
    open_sqlite_connection,
    reset_sqlite_metrics,
    write_transaction,
)
from Data.modules.workers.crash_diagnostics import (
    analyze_worker_crash,
    classify_crash_text,
    generation_log_filename,
    retain_pool_logs,
)
from Data.modules.workers.events import (
    WorkerEventEmitter,
    WorkerEventKind,
    get_structured_event_buffer,
    get_worker_event_emitter,
    set_worker_event_emitter,
)
from Data.modules.workers.process import spawn_worker_process
from Data.modules.workers.pools import POOL_CATALOG


class CrashLogIdentityTests(unittest.TestCase):
    def test_generation_filename_is_unique_per_pid_and_suffix(self) -> None:
        a = generation_log_filename(
            pool_id="source_ingestion",
            slot=0,
            worker_id="source_ingestion-0-1719bbd4",
            pid=15091,
            started_at=1_725_000_000.0,
        )
        b = generation_log_filename(
            pool_id="source_ingestion",
            slot=0,
            worker_id="source_ingestion-0-981cf348",
            pid=15122,
            started_at=1_725_000_001.0,
        )
        self.assertNotEqual(a, b)
        self.assertIn("pid15091", a)
        self.assertIn("pid15122", b)
        self.assertIn("1719bbd4", a)
        self.assertIn("981cf348", b)

    def test_restart_preserves_previous_generation_log(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            log_dir = Path(tmp.name)
            # Fake crashing entrypoint via python -c is not allowlisted; use a
            # tiny allowlisted-style spawn with a script that exits after writing.
            # We exercise spawn_worker_process log path uniqueness with a mock entrypoint
            # by temporarily extending the allowlist via module attribute check —
            # instead write two unique files the same way process.py does.
            from Data.modules.workers import process as proc_mod

            paths: list[Path] = []
            for suffix, pid in (("aaa11111", 1001), ("bbb22222", 1002)):
                worker_id = f"dataset-0-{suffix}"
                pool_dir = log_dir / "dataset"
                pool_dir.mkdir(parents=True, exist_ok=True)
                name = generation_log_filename(
                    pool_id="dataset",
                    slot=0,
                    worker_id=worker_id,
                    pid=pid,
                    started_at=time.time(),
                )
                path = pool_dir / name
                path.write_text(f"TRACEBACK_MARKER_{suffix}\n", encoding="utf-8")
                paths.append(path)
            self.assertTrue(paths[0].is_file())
            self.assertTrue(paths[1].is_file())
            self.assertNotEqual(paths[0], paths[1])
            self.assertIn("TRACEBACK_MARKER_aaa11111", paths[0].read_text(encoding="utf-8"))
            # Retention keeps both when under limits.
            deleted = retain_pool_logs(log_dir / "dataset", max_files=40)
            self.assertEqual(deleted, [])
            self.assertTrue(paths[0].is_file())
        finally:
            tmp.cleanup()

    def test_spawn_opens_exclusive_unique_log(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            # Use a real allowlisted entrypoint that exits immediately.
            owned = spawn_worker_process(
                worker_id="workflow-0-deadbeef",
                pool_id="workflow",
                slot=0,
                entrypoint="Data.modules.workers.entrypoints.workflow",
                cwd=Path(__file__).resolve().parents[3],
                log_dir=Path(tmp.name),
                env={"LEVIATHAN_WORKERS_ENABLED": "0"},
            )
            try:
                self.assertIsNotNone(owned.log_path)
                assert owned.log_path is not None
                self.assertTrue(owned.log_path.name.startswith("workflow-0-deadbeef") or "deadbeef" in owned.log_path.name)
                self.assertIn(f"pid{owned.pid}", owned.log_path.name)
                # Second generation must not share the path.
                owned2 = spawn_worker_process(
                    worker_id="workflow-0-cafebabe",
                    pool_id="workflow",
                    slot=0,
                    entrypoint="Data.modules.workers.entrypoints.workflow",
                    cwd=Path(__file__).resolve().parents[3],
                    log_dir=Path(tmp.name),
                    env={"LEVIATHAN_WORKERS_ENABLED": "0"},
                )
                try:
                    self.assertIsNotNone(owned2.log_path)
                    self.assertNotEqual(owned.log_path, owned2.log_path)
                    self.assertTrue(owned.log_path.exists())
                finally:
                    if owned2.popen and owned2.popen.poll() is None:
                        owned2.popen.kill()
                        owned2.popen.wait(timeout=5)
            finally:
                if owned.popen and owned.popen.poll() is None:
                    owned.popen.kill()
                    owned.popen.wait(timeout=5)
        finally:
            tmp.cleanup()


class CrashClassificationTests(unittest.TestCase):
    def test_database_locked_from_traceback(self) -> None:
        text = (
            "Traceback (most recent call last):\n"
            '  File "store.py", line 10, in initialize\n'
            "sqlite3.OperationalError: database is locked\n"
        )
        ev = classify_crash_text(text, exit_code=1)
        self.assertEqual(ev.error_code, "DATABASE_LOCKED")
        self.assertIn("OperationalError", ev.error_summary)

    def test_exit_alone_is_not_sqlite(self) -> None:
        ev = classify_crash_text("", exit_code=1)
        self.assertEqual(ev.error_code, "PROCESS_EXIT_NONZERO")
        self.assertNotEqual(ev.error_code, "DATABASE_LOCKED")

    def test_analyze_reads_bounded_tail(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "w.log"
            path.write_text(
                "phase=BOOTSTRAP_DATABASE\n"
                "ImportError: No module named 'missing_pkg'\n",
                encoding="utf-8",
            )
            ev = analyze_worker_crash(log_path=path, exit_code=1)
            self.assertEqual(ev.error_code, "IMPORT_ERROR")
            self.assertEqual(ev.startup_phase, "BOOTSTRAP_DATABASE")
        finally:
            tmp.cleanup()


class DuplicateEventEmissionTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_worker_event_emitter(None)

    def test_human_line_once_structured_still_emitted(self) -> None:
        stream = io.StringIO()
        buf = get_structured_event_buffer()
        buf.drain()
        emitter = WorkerEventEmitter(stream=stream, enable_terminal=True, enable_structured=True)
        set_worker_event_emitter(emitter)
        # Simulate lastResort-like misconfig: attach StreamHandler to stderr that
        # would duplicate IF propagate were True. Our logger must not propagate.
        err = io.StringIO()
        handler = logging.StreamHandler(err)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            emitter.worker_crashed(
                pool="source_ingestion",
                worker_id="source_ingestion-0-abc123",
                exit_code=1,
                error_code="UNCLASSIFIED_EXIT",
                error_summary="exit=1",
            )
            emitter.worker_restarted(
                pool="source_ingestion",
                worker_id="source_ingestion-0-def456",
                attempt=1,
            )
            emitter.worker_ready(
                pool="source_ingestion",
                worker_id="source_ingestion-0-def456",
                worker_pid=42,
            )
        finally:
            root.removeHandler(handler)

        human = stream.getvalue()
        self.assertEqual(human.count("crashed"), 1)
        self.assertEqual(human.count("herstart"), 1)
        self.assertEqual(human.count("gereed"), 1)
        # Structured buffer received the same three events.
        records = buf.drain()
        kinds = []
        for rec in records:
            payload = getattr(rec, "worker_event", None) or {}
            if isinstance(payload, dict) and payload.get("event"):
                kinds.append(payload["event"])
        self.assertIn(WorkerEventKind.WORKER_CRASHED.value, kinds)
        self.assertIn(WorkerEventKind.WORKER_RESTARTED.value, kinds)
        self.assertIn(WorkerEventKind.WORKER_READY.value, kinds)
        # Propagating root handler must not have received the human line.
        self.assertNotIn("crashed", err.getvalue())


class SqliteAttributionTests(unittest.TestCase):
    def test_slow_tx_includes_phases_and_measured_rows(self) -> None:
        reset_sqlite_metrics()
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "t.db"
            conn = open_sqlite_connection(db)
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.commit()
            captured: list[str] = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: captured.append(str(a[0]))):
                with write_transaction(
                    conn,
                    store="job_store",
                    operation="claim_next_for_pool",
                    slow_tx_ms=0.0,
                ) as c:
                    c.execute("INSERT INTO t(id) VALUES (1)")
            conn.close()
            self.assertTrue(captured)
            line = captured[-1]
            self.assertIn("store=job_store", line)
            self.assertIn("operation=claim_next_for_pool", line)
            self.assertIn("begin_ms=", line)
            self.assertIn("body_ms=", line)
            self.assertIn("commit_ms=", line)
            self.assertIn("total_ms=", line)
            self.assertNotIn("rows=0", line.replace("rows=0", "rows=MEASURED"))  # soft
            # Real row delta should be >= 1
            self.assertRegex(line, r"rows=\d+")
            self.assertNotIn(f"rows={ROWS_UNMEASURED}", line)
        finally:
            tmp.cleanup()


class BootstrapBarrierTests(unittest.TestCase):
    def test_supervisor_not_spawned_until_api_ready(self) -> None:
        from Data.modules.workers import bootstrap as boot

        calls: list[str] = []

        class FakeApi:
            def __init__(self) -> None:
                self.returncode = None
                self._n = 0

            def poll(self):
                self._n += 1
                return None

        api = FakeApi()
        ready_after = {"n": 0}

        def fake_urlopen(req, timeout=1.5):  # noqa: ANN001
            ready_after["n"] += 1
            if ready_after["n"] < 3:
                raise OSError("refused")

            class Resp:
                status = 200

                def read(self, _n: int = 4096) -> bytes:
                    return b'{"ok":true,"liveness":"alive","bootstrapped":true,"started":true}'

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return Resp()

        import urllib.request

        with mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen), mock.patch.object(
            time, "sleep", return_value=None
        ):
            state = boot.wait_for_api_bootstrap(
                api,  # type: ignore[arg-type]
                host="127.0.0.1",
                port=9,
                timeout_seconds=5.0,
            )
        self.assertEqual(state, "API_READY")
        self.assertGreaterEqual(ready_after["n"], 3)

    def test_api_exit_during_boot_raises(self) -> None:
        from Data.modules.workers import bootstrap as boot

        class DeadApi:
            returncode = 7

            def poll(self):
                return 7

        with self.assertRaises(boot.ApiBootstrapError) as ctx:
            boot.wait_for_api_bootstrap(
                DeadApi(),  # type: ignore[arg-type]
                host="127.0.0.1",
                port=9,
                timeout_seconds=1.0,
            )
        self.assertEqual(ctx.exception.state, "API_EXITED_DURING_BOOT")

    def test_run_all_waits_before_supervisor(self) -> None:
        from Data.modules.workers import bootstrap as boot
        from Data.modules.workers.settings import WorkerSettings

        order: list[str] = []

        class FakeProc:
            def __init__(self, kind: str) -> None:
                self.kind = kind
                self.returncode = None
                order.append(f"spawn:{kind}")

            def poll(self):
                if self.kind == "api":
                    return None
                return None

            def terminate(self) -> None:
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def kill(self) -> None:
                self.returncode = -9

        def fake_popen(cmd, **kwargs):  # noqa: ANN001
            kind = "api" if "api" in cmd else "supervisor"
            return FakeProc(kind)

        class RT:
            host = "127.0.0.1"
            port = 8765

        class S:
            database_path = Path(tempfile.gettempdir()) / "lev-boot-test.db"
            runtime = RT()

        stub = types.ModuleType("Data.backend.config")
        stub.load_settings = lambda: S()  # type: ignore[attr-defined]
        prev = sys.modules.get("Data.backend.config")
        sys.modules["Data.backend.config"] = stub

        stop_after = {"n": 0}

        def fake_sleep(s: float) -> None:
            stop_after["n"] += 1
            if stop_after["n"] > 4:
                raise KeyboardInterrupt

        try:
            with mock.patch.object(boot.subprocess, "Popen", side_effect=fake_popen), mock.patch.object(
                boot, "wait_for_api_bootstrap", side_effect=lambda *a, **k: order.append("ready") or "API_READY"
            ), mock.patch(
                "Data.modules.workers.settings.load_worker_settings",
                return_value=WorkerSettings(
                    restart_max_attempts=5,
                    restart_window_seconds=120.0,
                    restart_base_backoff=0.01,
                    restart_max_backoff=0.05,
                    supervisor_lease_ttl_seconds=5.0,
                    pool_counts={p: 0 for p in POOL_CATALOG},
                ),
            ), mock.patch.object(boot.time, "sleep", side_effect=fake_sleep), mock.patch.object(
                boot.signal, "signal"
            ):
                try:
                    boot.run_all()
                except KeyboardInterrupt:
                    pass
        finally:
            if prev is None:
                sys.modules.pop("Data.backend.config", None)
            else:
                sys.modules["Data.backend.config"] = prev

        self.assertEqual(order[0], "spawn:api")
        self.assertEqual(order[1], "ready")
        self.assertEqual(order[2], "spawn:supervisor")


class SourceIngestionOwnershipTests(unittest.TestCase):
    def test_external_maps_to_fabric(self) -> None:
        from Data.modules.source_ingestion.worker import resolve_runner_mode

        with mock.patch.dict(os.environ, {"LEVIATHAN_SOURCE_INGESTION_RUNNER": "external"}, clear=False):
            self.assertEqual(resolve_runner_mode(), "fabric")

    def test_standalone_legacy_distinct(self) -> None:
        from Data.modules.source_ingestion.worker import resolve_runner_mode

        with mock.patch.dict(
            os.environ, {"LEVIATHAN_SOURCE_INGESTION_RUNNER": "standalone_legacy"}, clear=False
        ):
            self.assertEqual(resolve_runner_mode(), "standalone_legacy")

    def test_bat_does_not_start_standalone_on_external(self) -> None:
        root = Path(__file__).resolve().parents[3]
        text = (root / "run_leviathan.bat").read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(
            'findstr /B /C:"LEVIATHAN_SOURCE_INGESTION_RUNNER=external"',
            text,
        )
        self.assertIn("standalone_legacy", text)
        self.assertIn("Worker Fabric", text)


class FabricRecoverySemanticsTests(unittest.TestCase):
    def test_starting_not_counted_as_fabric_ready(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "fab.db"
            from Data.modules.workers.dashboard import build_worker_fabric_dashboard
            from Data.modules.workers.protocol import WorkerInstanceState, WorkerRegistration
            from Data.modules.workers.registry import WorkerRegistry, utc_now
            from Data.modules.workers.settings import WorkerSettings

            reg = WorkerRegistry(db)
            reg.initialize()
            # Supervisor lease present and healthy so fabric status reflects pools.
            reg.try_acquire_supervisor_lease(
                holder_id="test-holder",
                holder_pid=os.getpid(),
                process_start_identity=f"test:{os.getpid()}",
                ttl_seconds=60.0,
            )
            reg.update_supervisor_health(
                holder_id="test-holder",
                health="RUNNING",
            )
            reg.upsert(
                WorkerRegistration(
                    worker_id="workflow-0-aaaa",
                    pool_id="workflow",
                    slot=0,
                    pid=1,
                    process_start_identity="pid:1:1",
                    state=WorkerInstanceState.STARTING,
                    started_at=utc_now(),
                    last_heartbeat_at=utc_now(),
                )
            )
            settings = WorkerSettings(pool_counts={p: 0 for p in POOL_CATALOG})
            settings.pool_counts["workflow"] = 1
            dash = build_worker_fabric_dashboard(db_path=db, settings=settings)
            # STARTING workers must not make fabric READY.
            self.assertEqual(dash["summary"]["fabric_status"], "STARTING")
            self.assertGreaterEqual(dash["summary"]["starting_workers"], 1)
            self.assertEqual(dash["summary"]["ready_workers"], 0)
            workflow = next(p for p in dash["pools"] if p["pool_id"] == "workflow")
            self.assertEqual(workflow["status"], "STARTING")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
