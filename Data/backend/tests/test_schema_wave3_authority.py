"""WAVE 3 — SCHEMA-001..006 canonical authority + fresh-install upgrade proof."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.backend.db_upgrade import (
    WAVE3_PRODUCT_TABLES,
    _ensure_runtime_bootstrap_schema,
    _wave3_table_is_stub,
    repair_domain_wave3_schemas,
    repair_incompatible_wave3_product_schemas,
    upgrade_all_databases,
)
from Data.backend.table_ownership import ownership_for
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.db_commit.handlers.dataset import _commit_index_batch
from Data.modules.db_commit.handlers.market_sim import _commit_events
from Data.modules.db_commit.handlers.source_ingestion import _commit_batch
from Data.modules.db_commit.types import CommitIntent, CommitReceiptStatus
from Data.modules.intelligence.assimilation import AssimilationService
from Data.modules.knowledge.pipeline.committer import KnowledgeCommitter
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import StreamEventType


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


# Stub DDL that historically conflicted with store initialize() schemas.
_STUB_DDL = """
CREATE TABLE provider_stream_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    event_type TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE intelligence_assimilation_receipts (
    receipt_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE knowledge_commit_receipts (
    receipt_id TEXT PRIMARY KEY,
    commit_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE source_ingestion_commit_records (
    record_id TEXT PRIMARY KEY,
    container_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE dataset_commit_index_rows (
    row_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE market_sim_commit_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
);
"""


class BootstrapMatchesStoresTests(unittest.TestCase):
    def test_bootstrap_ddl_matches_canonical_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        _ensure_runtime_bootstrap_schema(conn)
        expected = {
            "provider_stream_events": {"job_id", "sequence", "event_type", "timestamp", "payload_json"},
            "intelligence_assimilation_receipts": {
                "receipt_id",
                "kind",
                "ok",
                "payload_json",
            },
            "knowledge_commit_receipts": {
                "commit_id",
                "artifact_id",
                "receipt_json",
                "created_at",
            },
            "source_ingestion_commit_records": {
                "source_id",
                "record_id",
                "commit_id",
                "applied_at",
            },
            "dataset_commit_index_rows": {
                "dataset_id",
                "row_id",
                "commit_id",
                "applied_at",
            },
            "market_sim_commit_batches": {
                "run_id",
                "record_id",
                "kind",
                "commit_id",
                "applied_at",
            },
        }
        for table, need in expected.items():
            cols = _cols(conn, table)
            self.assertTrue(need.issubset(cols), f"{table}: missing {need - cols}")
            self.assertFalse(_wave3_table_is_stub(conn, table), table)

    def test_ownership_domains(self) -> None:
        self.assertEqual(ownership_for("provider_stream_events"), DatabaseDomain.CONTROL)
        self.assertEqual(
            ownership_for("intelligence_assimilation_receipts"), DatabaseDomain.CONTROL
        )
        self.assertEqual(ownership_for("knowledge_commit_receipts"), DatabaseDomain.KNOWLEDGE)
        self.assertEqual(
            ownership_for("source_ingestion_commit_records"), DatabaseDomain.KNOWLEDGE
        )
        self.assertEqual(ownership_for("dataset_commit_index_rows"), DatabaseDomain.KNOWLEDGE)
        self.assertEqual(ownership_for("market_sim_commit_batches"), DatabaseDomain.MARKET)


class StubRepairTests(unittest.TestCase):
    def test_repairs_all_six_stub_tables(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(_STUB_DDL)
        for table in WAVE3_PRODUCT_TABLES:
            self.assertTrue(_wave3_table_is_stub(conn, table), table)
        repaired = repair_incompatible_wave3_product_schemas(conn)
        self.assertEqual(set(repaired), set(WAVE3_PRODUCT_TABLES))
        for table in WAVE3_PRODUCT_TABLES:
            self.assertFalse(_wave3_table_is_stub(conn, table), table)

    def test_idempotent_when_already_canonical(self) -> None:
        conn = sqlite3.connect(":memory:")
        _ensure_runtime_bootstrap_schema(conn)
        self.assertEqual(repair_incompatible_wave3_product_schemas(conn), [])


class FreshInstallSchemaAuthorityTests(unittest.TestCase):
    def test_fresh_upgrade_creates_canonical_schemas_in_owned_domains(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_wave3_fresh_"))
        paths = DatabasePaths(
            control=root / "control.db",
            knowledge=root / "knowledge.db",
            market=root / "market.db",
        )
        report = upgrade_all_databases(paths)
        self.assertTrue(report.completed)
        self.assertEqual(len(list(root.glob("*.db"))), 3)

        control = sqlite3.connect(paths.control)
        knowledge = sqlite3.connect(paths.knowledge)
        market = sqlite3.connect(paths.market)
        try:
            # Owned tables present with canonical columns.
            self.assertIn("job_id", _cols(control, "provider_stream_events"))
            self.assertIn("kind", _cols(control, "intelligence_assimilation_receipts"))
            self.assertIn("artifact_id", _cols(knowledge, "knowledge_commit_receipts"))
            self.assertIn("source_id", _cols(knowledge, "source_ingestion_commit_records"))
            self.assertIn("commit_id", _cols(knowledge, "dataset_commit_index_rows"))
            self.assertIn("kind", _cols(market, "market_sim_commit_batches"))

            # Stores / handlers can initialize against upgrade output.
            ProviderStreamStore(paths.control).initialize()
            AssimilationService(database_path=paths.control)._ensure_sqlite()
            KnowledgeCommitter(paths.knowledge).initialize()

            intent = CommitIntent(
                commit_id="c1",
                idempotency_key="k1",
                domain="source_ingestion",
                operation="source_ingestion.commit_batch",
                payload_hash="h",
            )
            receipt = _commit_batch(
                intent,
                {"source_id": "s1", "records": [{"id": "r1", "x": 1}]},
                paths.knowledge,
                settings=type("S", (), {"max_batch_rows": 1000})(),
            )
            self.assertEqual(receipt.status, CommitReceiptStatus.APPLIED.value)

            d_intent = CommitIntent(
                commit_id="c2",
                idempotency_key="k2",
                domain="dataset",
                operation="dataset.commit_index_batch",
                payload_hash="h2",
            )
            d_receipt = _commit_index_batch(
                d_intent,
                {"dataset_id": "d1", "rows": [{"row_id": "row1"}]},
                paths.knowledge,
                settings=type("S", (), {"max_batch_rows": 1000})(),
            )
            self.assertEqual(d_receipt.status, CommitReceiptStatus.APPLIED.value)

            m_intent = CommitIntent(
                commit_id="c3",
                idempotency_key="k3",
                domain="market_sim",
                operation="market_sim.commit_events",
                payload_hash="h3",
                sequence_number=1,
            )
            m_receipt = _commit_events(
                m_intent,
                {"run_id": "run1", "events": [{"event_id": "e1"}]},
                paths.market,
                settings=type("S", (), {})(),
            )
            self.assertEqual(m_receipt.status, CommitReceiptStatus.APPLIED.value)

            store = ProviderStreamStore(paths.control)
            store.initialize()
            store.append("job-a", StreamEventType.DELTA, {"t": 1})
            events = store.read_after("job-a", 0)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].sequence, 1)
        finally:
            control.close()
            knowledge.close()
            market.close()

    def test_domain_repair_after_stub_injection(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_wave3_repair_"))
        paths = DatabasePaths(
            control=root / "c.db",
            knowledge=root / "k.db",
            market=root / "m.db",
        )
        upgrade_all_databases(paths)
        # Inject stubs into owned DBs (simulates historical incompatible install).
        for domain, path, tables in (
            (
                "CONTROL",
                paths.control,
                ("provider_stream_events", "intelligence_assimilation_receipts"),
            ),
            (
                "KNOWLEDGE",
                paths.knowledge,
                (
                    "knowledge_commit_receipts",
                    "source_ingestion_commit_records",
                    "dataset_commit_index_rows",
                ),
            ),
            ("MARKET", paths.market, ("market_sim_commit_batches",)),
        ):
            conn = sqlite3.connect(path)
            for table in tables:
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            conn.executescript(_STUB_DDL)
            conn.commit()
            conn.close()
            _ = domain

        repaired = repair_domain_wave3_schemas(paths)
        self.assertIn("provider_stream_events", repaired.get("CONTROL", []))
        self.assertIn("knowledge_commit_receipts", repaired.get("KNOWLEDGE", []))
        self.assertIn("market_sim_commit_batches", repaired.get("MARKET", []))

        with sqlite3.connect(paths.control) as conn:
            self.assertFalse(_wave3_table_is_stub(conn, "provider_stream_events"))
        with sqlite3.connect(paths.knowledge) as conn:
            self.assertFalse(_wave3_table_is_stub(conn, "dataset_commit_index_rows"))
        with sqlite3.connect(paths.market) as conn:
            self.assertFalse(_wave3_table_is_stub(conn, "market_sim_commit_batches"))


if __name__ == "__main__":
    unittest.main()
