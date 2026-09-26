"""WAVE 55+ — institutional_core / institutional_runtime migrations."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MIGRATIONS, MigrationRunner

EXPECTED_TABLES = {
    "institutional_instruments",
    "institutional_instrument_aliases",
    "institutional_breaks",
    "institutional_decision_packets",
    "institutional_audit_chain",
    "institutional_exceptions",
}

RUNTIME_TABLES = {
    "institutional_ibor_events",
    "institutional_journal_entries",
    "institutional_recon_runs",
    "institutional_mandates",
    "institutional_workflow_checkpoints",
    "institutional_valuation_snapshots",
    "institutional_bitemporal_records",
    "institutional_authority_approvals",
    "institutional_model_governance",
    "institutional_quarantine",
}


class InstitutionalMigrationW55Tests(unittest.TestCase):
    def test_head_includes_institutional_core(self) -> None:
        self.assertGreaterEqual(MIGRATIONS[-1].version, 55)
        names = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(names[55], "institutional_core")
        if MIGRATIONS[-1].version >= 56:
            self.assertEqual(names[56], "institutional_runtime")

    def test_upgrade_from_empty_creates_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "institutional_w55.sqlite"
            runner = MigrationRunner(path)
            applied = runner.apply_all()
            self.assertEqual(applied[0], 1)
            self.assertIn(55, applied)
            self.assertEqual(applied[-1], MIGRATIONS[-1].version)

            with sqlite3.connect(path) as conn:
                self.assertEqual(runner.current_version(conn), MIGRATIONS[-1].version)
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for name in EXPECTED_TABLES:
                    self.assertIn(name, tables)
                if MIGRATIONS[-1].version >= 56:
                    for name in RUNTIME_TABLES:
                        self.assertIn(name, tables)

                indexes = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    ).fetchall()
                }
                self.assertIn("idx_institutional_breaks_fingerprint", indexes)
                self.assertIn("idx_institutional_breaks_status", indexes)
                self.assertIn("idx_institutional_instrument_aliases_instrument", indexes)
                self.assertIn("idx_institutional_exceptions_status", indexes)

            second = MigrationRunner(path).apply_all()
            self.assertEqual(second, [])

    def test_audit_chain_seq_autoincrement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.sqlite"
            MigrationRunner(path).apply_all()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """
                    INSERT INTO institutional_audit_chain
                    (event_id, kind, actor, detail, ts, prev_hash, event_hash, metadata_json)
                    VALUES ('e1', 'test', 'tester', 'detail', 't0', '', 'h1', '{}')
                    """
                )
                conn.commit()
                row = conn.execute(
                    "SELECT seq, event_id FROM institutional_audit_chain"
                ).fetchone()
                self.assertEqual(row[0], 1)
                self.assertEqual(row[1], "e1")


if __name__ == "__main__":
    unittest.main()
