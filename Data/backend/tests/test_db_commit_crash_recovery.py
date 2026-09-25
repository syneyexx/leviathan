"""DB Commit Coordinator — crash recovery + inflight reclaim."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.db_commit.producer import CommitProducer
from Data.modules.db_commit.settings import DbCommitSettings
from Data.modules.db_commit.spool import CommitSpool
from Data.modules.db_commit.types import CommitIntent, CommitReceipt, CommitReceiptStatus
from Data.modules.db_commit.writer import DbCommitCoordinator


class CrashRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "leviathan.db"
        MigrationRunner(self.db).apply_all()
        self.settings = DbCommitSettings(enabled=True, poll_seconds=0.01)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_crash_before_commit_requeues(self) -> None:
        coord = DbCommitCoordinator(self.db, settings=self.settings)
        coord.startup()
        producer = CommitProducer(
            self.db, settings=self.settings, spool=coord.spool, receipts=coord.receipts
        )
        result = producer.submit(
            operation="system.echo_records",
            domain="system",
            payload={"records": [{"id": "pre1"}]},
            idempotency_key="crash-before",
        )
        item = coord.spool.claim_next()
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.intent.commit_id, result.commit_id)
        # Simulate writer death while inflight (no DB commit yet).
        coord.shutdown()

        coord2 = DbCommitCoordinator(self.db, settings=self.settings)
        coord2.startup()
        pending = coord2.spool.stats().pending_count
        self.assertGreaterEqual(pending, 1)
        coord2.process_until_idle()
        receipt = coord2.receipts.get_by_idempotency_key("crash-before")
        self.assertIsNotNone(receipt)
        coord2.shutdown()

    def test_crash_after_commit_before_spool_finalize(self) -> None:
        coord = DbCommitCoordinator(self.db, settings=self.settings)
        coord.startup()
        producer = CommitProducer(
            self.db, settings=self.settings, spool=coord.spool, receipts=coord.receipts
        )
        result = producer.submit(
            operation="system.echo_records",
            domain="system",
            payload={"records": [{"id": "post1"}, {"id": "post2"}]},
            idempotency_key="crash-after",
        )
        item = coord.spool.claim_next()
        assert item is not None
        # Manually apply + persist receipt, leave inflight file (crash before finalize).
        payload = json.loads(Path(item.intent.payload_ref).read_text(encoding="utf-8"))
        handler = coord.registry.get(item.intent.operation)
        receipt = handler.apply(
            item.intent, payload, db_path=self.db, settings=self.settings
        )
        coord.receipts.persist(receipt)
        # Leave file in inflight/
        self.assertTrue(item.path.is_file())
        coord.shutdown()

        coord2 = DbCommitCoordinator(self.db, settings=self.settings)
        coord2.startup()
        # Recovery should finalize without duplicating.
        self.assertEqual(coord2.spool.stats().inflight_count, 0)
        again = CommitProducer(
            self.db, settings=self.settings, spool=coord2.spool, receipts=coord2.receipts
        ).submit(
            operation="system.echo_records",
            domain="system",
            payload={"records": [{"id": "post1"}, {"id": "post2"}]},
            idempotency_key="crash-after",
        )
        self.assertTrue(again.committed)
        # Domain rows must remain unique.
        conn = __import__("sqlite3").connect(self.db)
        try:
            n = conn.execute("SELECT COUNT(*) FROM db_commit_echo_records").fetchone()[0]
            self.assertEqual(int(n), 2)
        finally:
            conn.close()
        coord2.shutdown()

    def test_corrupt_intent_quarantined(self) -> None:
        spool = CommitSpool(
            self.settings.spool_root_for(self.db), settings=self.settings
        )
        bad = spool.dir("pending") / "corrupt.json"
        bad.write_text("{not-json", encoding="utf-8")
        items = spool.iter_pending()
        self.assertEqual(items, [])
        self.assertGreaterEqual(spool.stats().quarantine_count, 1)

    def test_shutdown_leaves_pending_recoverable(self) -> None:
        coord = DbCommitCoordinator(self.db, settings=self.settings)
        coord.startup()
        producer = CommitProducer(
            self.db, settings=self.settings, spool=coord.spool, receipts=coord.receipts
        )
        for i in range(5):
            producer.submit(
                operation="system.echo_records",
                domain="system",
                payload={"records": [{"id": f"s{i}"}]},
                idempotency_key=f"shutdown-{i}",
            )
        # Process only one, then drain/shutdown with backlog.
        coord.process_one()
        pending_before = coord.spool.stats().pending_count
        self.assertGreaterEqual(pending_before, 1)
        coord.shutdown()

        coord2 = DbCommitCoordinator(self.db, settings=self.settings)
        coord2.startup()
        coord2.process_until_idle()
        for i in range(5):
            self.assertIsNotNone(coord2.receipts.get_by_idempotency_key(f"shutdown-{i}"))
        coord2.shutdown()


if __name__ == "__main__":
    unittest.main()
