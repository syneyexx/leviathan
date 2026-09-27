"""WAVE 8/10/12/13 focused regression for stream, truth, market, obs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from Data.modules.common.db_contention import three_database_contention_snapshot
from Data.modules.db_commit.handlers.source_ingestion import _commit_brain_sync
from Data.modules.db_commit.types import CommitIntent, CommitReceiptStatus
from Data.modules.model_runtime.serving import (
    ServingSupervisor,
    WorkerState,
    reset_serving_supervisor_for_tests,
)
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import StreamEventType


class ProviderStreamDurabilityTests(unittest.TestCase):
    def test_sequence_survives_process_local_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "control.db"
            a = ProviderStreamStore(db)
            a.initialize()
            e1 = a.append("job-1", StreamEventType.DELTA, {"t": 1})
            e2 = a.append("job-1", StreamEventType.DELTA, {"t": 2})
            self.assertEqual(e1.sequence, 1)
            self.assertEqual(e2.sequence, 2)
            # New process-local instance must continue from durable MAX(sequence).
            b = ProviderStreamStore(db)
            e3 = b.append("job-1", StreamEventType.DELTA, {"t": 3})
            self.assertEqual(e3.sequence, 3)
            events = b.read_after("job-1", 0)
            self.assertEqual([e.sequence for e in events], [1, 2, 3])


class ServingStderrAndOrphanTests(unittest.TestCase):
    def test_stock_supervisor_defaults_to_durable_registry(self) -> None:
        import os

        from Data.modules.model_runtime.serving import (
            default_serving_registry_path,
            get_serving_supervisor,
            reset_serving_supervisor_for_tests,
        )

        # Clear process singleton so stock get_serving_supervisor() is exercised.
        reset_serving_supervisor_for_tests(registry_path=None)
        # Ensure env override is not set for this assertion.
        old = os.environ.pop("LEVIATHAN_SERVING_REGISTRY_PATH", None)
        try:
            # Force re-init via get after clearing singleton with None path.
            import Data.modules.model_runtime.serving as serving_mod

            serving_mod._GLOBAL_SUPERVISOR = None
            supervisor = get_serving_supervisor()
            expected = default_serving_registry_path()
            self.assertIsNotNone(supervisor.registry_path)
            self.assertEqual(Path(supervisor.registry_path).resolve(), expected.resolve())
        finally:
            if old is not None:
                os.environ["LEVIATHAN_SERVING_REGISTRY_PATH"] = old
            reset_serving_supervisor_for_tests(registry_path=None)

    def test_stderr_pipe_is_drained_for_noisy_child(self) -> None:
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "serving.json"
            supervisor = reset_serving_supervisor_for_tests(registry_path=registry)
            # Child floods stderr; without drain this can deadlock on PIPE buffer.
            worker = supervisor.start_subprocess(
                provider_id="p",
                model_id="m",
                backend_kind="test",
                command=[
                    sys.executable,
                    "-c",
                    "import sys,time;\n"
                    "[sys.stderr.write('x'*1024) or sys.stderr.flush() for _ in range(200)];\n"
                    "time.sleep(0.2)",
                ],
                endpoint="http://127.0.0.1:9/v1",
                ready_timeout_seconds=5.0,
                ready_check=lambda: True,
            )
            self.assertIn(worker.state, {WorkerState.READY, WorkerState.UNHEALTHY, WorkerState.DEAD})
            # Drain thread should have captured a non-empty bounded tail eventually.
            # (READY path returns before process exit; wait briefly for drain.)
            import time

            time.sleep(0.3)
            # Must not hang; registry should exist after start.
            self.assertTrue(registry.is_file())

    def test_orphan_reconcile_does_not_kill_on_pid_reuse(self) -> None:
        import json
        import os

        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "serving.json"
            # Persist a fake prior worker with our own PID but wrong fingerprint.
            registry.write_text(
                json.dumps(
                    {
                        "workers": [
                            {
                                "worker_id": "w-old",
                                "provider_id": "p",
                                "model_id": "m",
                                "backend_kind": "vllm_class",
                                "endpoint": "http://127.0.0.1:9/v1",
                                "state": "READY",
                                "pid": os.getpid(),
                                "pid_fingerprint": "not-a-real-fingerprint",
                                "started_at": "2020-01-01T00:00:00Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            supervisor = ServingSupervisor(registry_path=registry)
            workers = supervisor.list_workers()
            self.assertEqual(len(workers), 1)
            self.assertEqual(workers[0].state, WorkerState.DEAD)
            self.assertTrue(workers[0].metadata.get("orphan_reconciled"))
            # Our process must still be alive (not killed).
            os.kill(os.getpid(), 0)


class TruthBrainSyncTests(unittest.TestCase):
    def test_brain_sync_rejects_when_container_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "knowledge.db"
            intent = CommitIntent(
                commit_id="c1",
                idempotency_key="k1",
                operation="source_ingestion.commit_brain_sync",
                domain="source_ingestion",
            )
            receipt = _commit_brain_sync(
                intent,
                {"source_id": "missing-source", "sync": {"ok": True}},
                db,
                SimpleNamespace(),
            )
            self.assertEqual(receipt.status, CommitReceiptStatus.REJECTED.value)
            self.assertEqual(receipt.error_code, "AUXILIARY_PERSISTENCE_FAILED")


class MarketFeedIdentityTests(unittest.TestCase):
    def test_default_feed_id_not_pid_only(self) -> None:
        import inspect

        from Data.modules.provider_io.adapters import market_stream as ms

        src = inspect.getsource(ms.MarketStreamAdapter._execute_stream)
        self.assertNotIn('f"feed_{os.getpid()}"', src)
        self.assertIn("feed_", src)
        # Identity digests provider+symbols — PID alone is forbidden.
        self.assertIn("digest", src)


class ObsThreeDbTests(unittest.TestCase):
    def test_three_db_contention_exposes_domains_or_unmeasured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "c.db"
            knowledge = root / "k.db"
            market = root / "m.db"
            control.write_bytes(b"x" * 32)
            knowledge.write_bytes(b"y" * 64)
            # market intentionally missing → UNMEASURED sizes still honest
            paths = SimpleNamespace(control=control, knowledge=knowledge, market=market)
            snap = three_database_contention_snapshot(paths)
            self.assertIn("CONTROL", snap["domains"])
            self.assertIn("KNOWLEDGE", snap["domains"])
            self.assertIn("MARKET", snap["domains"])
            self.assertEqual(snap["domains"]["CONTROL"]["dbFileSize"], 32)
            self.assertEqual(snap["domains"]["KNOWLEDGE"]["dbFileSize"], 64)
            self.assertEqual(snap["domains"]["MARKET"]["dbFileSize"], "UNMEASURED")
            self.assertTrue(snap["truth"]["unmeasuredIsNotZero"])


if __name__ == "__main__":
    unittest.main()
