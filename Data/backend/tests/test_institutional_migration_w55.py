"""WAVE 55 — institutional_core migration creates additive tables."""

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


class InstitutionalMigrationW55Tests(unittest.TestCase):
    def test_head_is_55(self) -> None:
        self.assertEqual(MIGRATIONS[-1].version, 55)
        self.assertEqual(MIGRATIONS[-1].name, "institutional_core")

    def test_upgrade_from_empty_creates_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "institutional_w55.sqlite"
            runner = MigrationRunner(path)
            applied = runner.apply_all()
            self.assertEqual(applied, list(range(1, 56)))
            self.assertEqual(applied[-1], 55)

            with sqlite3.connect(path) as conn:
                self.assertEqual(runner.current_version(conn), 55)
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for name in EXPECTED_TABLES:
                    self.assertIn(name, tables)

                # Indexes present for fingerprint / status / instrument_id
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

            # Idempotent re-apply
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
