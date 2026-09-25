"""DB Commit Coordinator — domain integration + anti-pattern guards."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.db_commit.domain_submit import (
    submit_dataset_index_batch,
    submit_evaluation_results,
    submit_knowledge_prepared,
    submit_market_sim_events,
    submit_research_evidence,
    submit_source_ingestion_batch,
    submit_training_lineage,
)
from Data.modules.db_commit.settings import DbCommitSettings
from Data.modules.db_commit.writer import DbCommitCoordinator
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class DomainIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "leviathan.db"
        MigrationRunner(self.db).apply_all()
        self.settings = DbCommitSettings(enabled=True, poll_seconds=0.01)
        self.coord = DbCommitCoordinator(self.db, settings=self.settings)
        self.coord.startup()

    def tearDown(self) -> None:
        self.coord.shutdown()
        self.tmp.cleanup()

    def _drain(self) -> None:
        self.coord.process_until_idle()

    def test_knowledge_prepared(self) -> None:
        result = submit_knowledge_prepared(
            self.db,
            artifact={
                "artifact_id": "art-1",
                "artifact_type": "generic",
                "producer": "test",
                "producer_version": "1",
                "title": "book.pdf",
                "content_inline": "hello knowledge",
            },
            title="book.pdf",
            idempotency_key="k-1",
        )
        self.assertTrue(result.accepted)
        self._drain()
        receipt = self.coord.receipts.get_by_idempotency_key("k-1")
        self.assertIsNotNone(receipt)

    def test_research_evidence(self) -> None:
        result = submit_research_evidence(
            self.db,
            project_id="proj-1",
            evidence=[{"evidence_id": "e1", "text": "fact"}],
            title="Quantum computing",
            idempotency_key="r-1",
        )
        self.assertTrue(result.accepted)
        self._drain()
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("r-1"))

    def test_dataset_index_batch(self) -> None:
        rows = [{"row_id": f"r{i}", "text": f"row-{i}"} for i in range(50)]
        result = submit_dataset_index_batch(
            self.db,
            dataset_id="python-code",
            rows=rows,
            title="python-code",
            idempotency_key="d-1",
        )
        self.assertTrue(result.accepted)
        self._drain()
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("d-1"))

    def test_source_ingestion_batch(self) -> None:
        result = submit_source_ingestion_batch(
            self.db,
            source_id="src-1",
            records=[{"id": "rec1", "path": "a.pdf"}],
            title="archive",
            idempotency_key="si-1",
        )
        self.assertTrue(result.accepted)
        self._drain()
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("si-1"))

    def test_market_sim_events(self) -> None:
        result = submit_market_sim_events(
            self.db,
            run_id="run-1",
            events=[{"event_id": "ev1", "kind": "tick"}],
            fills=[{"fill_id": "f1", "qty": 1}],
            idempotency_key="ms-1",
            sequence_number=1,
        )
        self.assertTrue(result.accepted)
        self._drain()
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("ms-1"))

    def test_evaluation_and_training(self) -> None:
        ev = submit_evaluation_results(
            self.db,
            evaluation_id="eval-1",
            results=[{"case_id": "c1", "score": 0.5}],
            idempotency_key="ev-1",
        )
        tr = submit_training_lineage(
            self.db,
            training_job_id="train-1",
            lineage={"step": 1},
            artifacts=[{"artifact_id": "a1"}],
            idempotency_key="tr-1",
        )
        self.assertTrue(ev.accepted)
        self.assertTrue(tr.accepted)
        self._drain()
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("ev-1"))
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("tr-1"))


class AntiPatternTests(unittest.TestCase):
    def test_no_dual_knowledge_writer_pool(self) -> None:
        self.assertEqual(POOL_CATALOG["db_commit"].default_count, 1)
        self.assertEqual(POOL_CATALOG["db_commit"].max_count, 1)
        self.assertEqual(POOL_CATALOG["knowledge_commit"].default_count, 0)
        self.assertEqual(pool_for_capability("knowledge.commit"), "db_commit")

    def test_writer_unavailable_does_not_require_direct_fallback(self) -> None:
        """Producer must spool when IPC is down — never imply direct heavy write."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "leviathan.db"
            MigrationRunner(db).apply_all()
            from Data.modules.db_commit.producer import CommitProducer
            from Data.modules.db_commit.types import AckStatus

            producer = CommitProducer(db)
            result = producer.submit(
                operation="system.noop",
                domain="system",
                payload={},
                idempotency_key="offline-1",
            )
            self.assertIn(
                result.ack_status,
                {AckStatus.ACCEPTED_TO_SPOOL.value, AckStatus.ACCEPTED_TO_WRITER.value},
            )


if __name__ == "__main__":
    unittest.main()
