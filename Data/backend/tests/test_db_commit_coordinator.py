"""DB Commit Coordinator — core types, receipts, handlers, producer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.common.sqlite_policy import WriteClass, open_sqlite_connection, ensure_wal
from Data.modules.db_commit.errors import UnknownOperationError
from Data.modules.db_commit.handlers.registry import build_default_registry
from Data.modules.db_commit.producer import CommitProducer
from Data.modules.db_commit.receipts import CommitReceiptStore
from Data.modules.db_commit.settings import DbCommitSettings
from Data.modules.db_commit.types import (
    AckStatus,
    CommitIntent,
    CommitPriority,
    CommitReceipt,
    CommitReceiptStatus,
)
from Data.modules.db_commit.writer import DbCommitCoordinator
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class SqlitePolicyTests(unittest.TestCase):
    def test_wal_once_and_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            conn = open_sqlite_connection(db, set_wal=False)
            try:
                row = conn.execute("PRAGMA busy_timeout").fetchone()
                self.assertGreaterEqual(int(row[0]), 1000)
                mode = ensure_wal(conn)
                self.assertEqual(mode, "wal")
            finally:
                conn.close()

    def test_write_class_enum(self) -> None:
        self.assertEqual(WriteClass.CONTROL_WRITE.value, "CONTROL_WRITE")
        self.assertEqual(WriteClass.COMMIT_WRITE.value, "COMMIT_WRITE")


class CommitTypesTests(unittest.TestCase):
    def test_intent_roundtrip(self) -> None:
        intent = CommitIntent.create(
            operation="system.echo_records",
            domain="system",
            priority=CommitPriority.P3_BULK,
            record_count_hint=3,
            safe_human_title="demo",
        )
        restored = CommitIntent.from_json(intent.to_json())
        self.assertEqual(restored.commit_id, intent.commit_id)
        self.assertEqual(restored.operation, "system.echo_records")
        self.assertEqual(restored.priority_enum(), CommitPriority.P3_BULK)

    def test_handler_registry_allowlist(self) -> None:
        reg = build_default_registry()
        self.assertTrue(reg.has("knowledge.commit_prepared"))
        self.assertTrue(reg.has("research.commit_evidence"))
        self.assertTrue(reg.has("dataset.commit_index_batch"))
        self.assertTrue(reg.has("market_sim.commit_events"))
        self.assertTrue(reg.has("evaluation.commit_results"))
        self.assertTrue(reg.has("training.commit_lineage"))
        with self.assertRaises(UnknownOperationError):
            reg.get("execute_sql")


class ReceiptIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "leviathan.db"
        MigrationRunner(self.db).apply_all()
        self.receipts = CommitReceiptStore(self.db)
        self.receipts.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_persist_and_lookup(self) -> None:
        receipt = CommitReceipt(
            commit_id="c1",
            idempotency_key="idem-1",
            domain="system",
            operation="system.noop",
            status=CommitReceiptStatus.APPLIED.value,
            record_count=0,
        )
        self.receipts.persist(receipt)
        by_id = self.receipts.get_by_commit_id("c1")
        by_key = self.receipts.get_by_idempotency_key("idem-1")
        self.assertIsNotNone(by_id)
        self.assertIsNotNone(by_key)
        assert by_key is not None
        self.assertEqual(by_key.commit_id, "c1")


class CoordinatorApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "leviathan.db"
        MigrationRunner(self.db).apply_all()
        self.settings = DbCommitSettings(enabled=True, max_batch_rows=100, poll_seconds=0.01)
        self.coord = DbCommitCoordinator(self.db, settings=self.settings)
        self.coord.startup()
        self.producer = CommitProducer(
            self.db,
            settings=self.settings,
            spool=self.coord.spool,
            receipts=self.coord.receipts,
        )

    def tearDown(self) -> None:
        self.coord.shutdown()
        self.tmp.cleanup()

    def test_submit_and_apply_echo(self) -> None:
        result = self.producer.submit(
            operation="system.echo_records",
            domain="system",
            payload={"records": [{"id": "a"}, {"id": "b"}]},
            idempotency_key="echo-1",
            safe_human_title="echo",
            record_count_hint=2,
        )
        self.assertTrue(result.accepted)
        n = self.coord.process_until_idle()
        self.assertGreaterEqual(n, 1)
        receipt = self.coord.receipts.get_by_idempotency_key("echo-1")
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt.status, CommitReceiptStatus.APPLIED.value)
        self.assertEqual(receipt.record_count, 2)

    def test_exactly_once_effect(self) -> None:
        payload = {"records": [{"id": "x1"}, {"id": "x2"}, {"id": "x3"}]}
        r1 = self.producer.submit(
            operation="system.echo_records",
            domain="system",
            payload=payload,
            idempotency_key="once-1",
        )
        self.coord.process_until_idle()
        r2 = self.producer.submit(
            operation="system.echo_records",
            domain="system",
            payload=payload,
            idempotency_key="once-1",
        )
        self.assertEqual(r2.ack_status, AckStatus.ALREADY_APPLIED.value)
        self.assertTrue(r2.committed)
        # Second delivery must not create another pending apply.
        before = self.coord.spool.stats().pending_count
        self.coord.process_until_idle()
        after = self.coord.spool.stats().pending_count
        self.assertEqual(before, after)
        self.assertEqual(r1.commit_id, r2.receipt.commit_id if r2.receipt else r1.commit_id)

    def test_hash_mismatch_quarantine(self) -> None:
        result = self.producer.submit(
            operation="system.echo_records",
            domain="system",
            payload={"records": [{"id": "q1"}]},
            idempotency_key="bad-hash",
        )
        # Tamper payload file after enqueue.
        path = Path(result.intent.payload_ref)
        path.write_text('{"records":[{"id":"tampered"}]}', encoding="utf-8")
        self.coord.process_until_idle()
        stats = self.coord.spool.stats()
        self.assertGreaterEqual(stats.quarantine_count, 1)


class PoolCatalogTests(unittest.TestCase):
    def test_db_commit_pool(self) -> None:
        defn = POOL_CATALOG["db_commit"]
        self.assertEqual(defn.default_count, 1)
        self.assertEqual(defn.max_count, 1)
        self.assertIn("IO_HEAVY", defn.resource_classes)
        self.assertEqual(pool_for_capability("knowledge.commit"), "db_commit")
        self.assertEqual(POOL_CATALOG["knowledge_commit"].default_count, 0)


if __name__ == "__main__":
    unittest.main()
