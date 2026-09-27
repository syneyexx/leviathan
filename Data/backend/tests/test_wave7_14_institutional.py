"""WAVE 7–14 remaining institutional defect regressions."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from Data.modules.backup import (
    RESTORE_NEW_SET_ACTIVE,
    BackupService,
)
from Data.modules.common.db_contention import three_database_contention_snapshot
from Data.modules.db_commit.handlers.dataset import _commit_index_batch
from Data.modules.db_commit.types import CommitIntent, CommitReceiptStatus
from Data.modules.execution.data_analysis import safe_calculate
from Data.modules.model_runtime.serving import (
    ServingSupervisor,
    WorkerState,
    reset_serving_supervisor_for_tests,
)
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import StreamEventType
from Data.modules.research.service import ResearchService
from Data.modules.research.store import ResearchStore


class Numeric001Tests(unittest.TestCase):
    def test_safe_calculate_delegates(self) -> None:
        ok = safe_calculate("(2+3)*4")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["value"], 20.0)
        self.assertEqual(ok["truth"]["delegates_to"], "NumericComputeEngine")
        bad = safe_calculate("__import__('os').system('x')")
        self.assertFalse(bad["ok"])


class ProviderStreamTests(unittest.TestCase):
    def test_durable_sequence_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            a = ProviderStreamStore(db)
            a.initialize()
            a.append("job1", StreamEventType.DELTA, {"n": 1})
            a.append("job1", StreamEventType.DELTA, {"n": 2})
            # New process-equivalent instance must continue sequences from DB.
            b = ProviderStreamStore(db)
            b.initialize()
            ev = b.append("job1", StreamEventType.DELTA, {"n": 3})
            self.assertEqual(ev.sequence, 3)
            events = b.read_after("job1", 0)
            self.assertEqual([e.sequence for e in events], [1, 2, 3])

    def test_connect_uses_sqlite_policy(self) -> None:
        src = Path("Data/modules/provider_io/stream_store.py").read_text(encoding="utf-8")
        self.assertIn("open_sqlite_connection", src)
        self.assertNotIn("PRAGMA journal_mode=WAL", src.replace(" ", ""))


class TruthTests(unittest.TestCase):
    def test_source_ingestion_failure_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "research.db"
            store = ResearchStore(db)
            store.initialize()
            svc = ResearchService(store, knowledge_database_path=None, knowledge=None)
            # Without knowledge path / store, SI init fails with configuration_error.
            self.assertIsNone(svc.source_ingestion)
            status = getattr(svc, "source_ingestion_status", {})
            self.assertEqual(status.get("state"), "UNAVAILABLE")
            self.assertEqual(status.get("reason"), "configuration_error")
            self.assertTrue(status.get("truth", {}).get("silent_none_forbidden"))

    def test_dataset_commit_rejects_after_auxiliary_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            intent = CommitIntent(
                commit_id="c1",
                idempotency_key="k1",
                domain="dataset",
                operation="dataset.commit_index_batch",
                payload_hash="h",
            )
            # Force DatasetStore.get_dataset to say present, update_dataset to fail.
            with mock.patch(
                "Data.modules.datasets.store.DatasetStore.initialize", lambda self: None
            ), mock.patch(
                "Data.modules.datasets.store.DatasetStore.get_dataset",
                return_value=object(),
            ), mock.patch(
                "Data.modules.datasets.store.DatasetStore.update_dataset",
                side_effect=RuntimeError("aux boom"),
            ):
                receipt = _commit_index_batch(
                    intent,
                    {"dataset_id": "d1", "rows": [{"row_id": "r1"}]},
                    db,
                    settings=SimpleNamespace(max_batch_rows=1000),
                )
            self.assertEqual(receipt.status, CommitReceiptStatus.REJECTED.value)
            self.assertFalse(receipt.result.get("auxiliary_metadata_ok"))


class Obs001Tests(unittest.TestCase):
    def test_per_domain_contention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(
                control=root / "c.db",
                knowledge=root / "k.db",
                market=root / "m.db",
            )
            for p in (paths.control, paths.knowledge, paths.market):
                sqlite3.connect(p).close()
            snap = three_database_contention_snapshot(paths)
            self.assertIn("CONTROL", snap["domains"])
            self.assertIn("KNOWLEDGE", snap["domains"])
            self.assertIn("MARKET", snap["domains"])
            self.assertTrue(snap["truth"]["perDomain"])
            self.assertTrue(snap["truth"]["notControlOnly"])
            # Measured file size is an int (may be 0 for empty fresh files) — not UNMEASURED.
            self.assertIsInstance(snap["domains"]["CONTROL"].get("dbFileSize"), int)
            self.assertIsInstance(snap["domains"]["KNOWLEDGE"].get("dbFileSize"), int)
            self.assertIsInstance(snap["domains"]["MARKET"].get("dbFileSize"), int)


class ModelServingTests(unittest.TestCase):
    def test_stderr_drain_helper_exists(self) -> None:
        self.assertTrue(hasattr(ServingSupervisor, "_start_stderr_drain"))

    def test_orphan_reconcile_stale_pid_not_killed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "serving_registry.json"
            reg.write_text(
                json.dumps(
                    {
                        "workers": [
                            {
                                "worker_id": "w-orphan",
                                "provider_id": "local",
                                "model_id": "m1",
                                "backend_kind": "vllm_class",
                                "endpoint": "http://127.0.0.1:9",
                                "state": "READY",
                                "pid": 99999999,
                                "started_at": "2020-01-01T00:00:00Z",
                                "pid_fingerprint": "99999999:1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            sup = reset_serving_supervisor_for_tests(registry_path=reg)
            workers = list(sup.list_workers())
            orphan = next(w for w in workers if w.worker_id == "w-orphan")
            self.assertEqual(orphan.state, WorkerState.DEAD)
            self.assertTrue(orphan.metadata.get("orphan_reconciled"))
            self.assertIn("not killed", (orphan.last_error or "").lower())


class Cleanup002Tests(unittest.TestCase):
    def test_ci_workflow_excludes_data_hades(self) -> None:
        text = Path(".github/workflows/leviathan-ci.yml").read_text(encoding="utf-8")
        self.assertIn('Path("Data/HADES")', text)
        self.assertNotIn('Path("HADES").exists()', text)

    def test_audit_script_three_db_default(self) -> None:
        text = Path("scripts/audit_large_db_payloads.py").read_text(encoding="utf-8")
        self.assertIn("audit_canonical_domains", text)
        self.assertIn("three_database", text)
        self.assertIn("boundedMode", text)


class MarketIdentityTests(unittest.TestCase):
    def test_feed_id_not_pid_only(self) -> None:
        text = Path("Data/modules/provider_io/adapters/market_stream.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('f"feed_{os.getpid()}"', text)
        self.assertIn("MARKET-002", text)
        self.assertIn("DEGRADED_GAP", text)


class BackupAtomicityTruthTests(unittest.TestCase):
    def test_manifest_declares_non_atomic_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "c.db"
            knowledge = root / "k.db"
            market = root / "m.db"
            for p, name in ((control, "c"), (knowledge, "k"), (market, "m")):
                with sqlite3.connect(p) as conn:
                    conn.execute(
                        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
                    )
                    conn.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (1, ?, 'now')",
                        (name,),
                    )
            svc = BackupService(
                database_path=control,
                artifacts_root=root / "art",
                backup_root=root / "bak",
                database_paths=SimpleNamespace(
                    control=control, knowledge=knowledge, market=market
                ),
            )
            (root / "art").mkdir()
            manifest = svc.create()
            truth = manifest.public_dict()["truth"]
            self.assertTrue(truth["crossFileRestoreIsNotAtomic"])
            restored = svc.restore(
                manifest.backup_id,
                confirm=True,
                maintenance_proof=svc.maintenance.enter_for_restore(reason="w7-14"),
            )
            self.assertEqual(
                restored.metadata.get("restoreTerminalState"), RESTORE_NEW_SET_ACTIVE
            )


if __name__ == "__main__":
    unittest.main()
