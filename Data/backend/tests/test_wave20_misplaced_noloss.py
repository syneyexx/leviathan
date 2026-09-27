"""WAVE 20 — misplaced-table reconciliation must be provably no-loss."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.db_upgrade import (
    MISPLACED_BLOCK_OPERATOR_REVIEW,
    MISPLACED_BLOCK_UNKNOWN,
    MISPLACED_EQUIVALENT_RETIRE,
    MISPLACED_MIGRATE,
    MISPLACED_SKIP_EMPTY,
    detect_misplaced_product_tables,
    reconcile_misplaced_product_tables,
    upgrade_all_databases,
)
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths


def _paths(root: Path) -> DatabasePaths:
    return DatabasePaths(
        control=root / "control.db",
        knowledge=root / "knowledge.db",
        market=root / "market.db",
    )


def _init_empty_three(paths: DatabasePaths) -> None:
    for p in (paths.control, paths.knowledge, paths.market):
        p.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE IF NOT EXISTS _boot(x INTEGER)")
        con.commit()
        con.close()


class MisplacedDetectFailClosedTests(unittest.TestCase):
    def test_unreadable_source_count_blocks_not_migrate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _init_empty_three(paths)
            con = sqlite3.connect(paths.control)
            con.execute(
                "CREATE TABLE knowledge_documents(id TEXT PRIMARY KEY, title TEXT)"
            )
            con.execute(
                "INSERT INTO knowledge_documents(id, title) VALUES ('a','t')"
            )
            con.commit()
            con.close()

            real_row_count = __import__(
                "Data.backend.db_upgrade", fromlist=["_row_count"]
            )._row_count

            def boom(conn, table):  # noqa: ANN001
                if table == "knowledge_documents":
                    raise sqlite3.OperationalError("disk I/O error")
                return real_row_count(conn, table)

            with mock.patch("Data.backend.db_upgrade._row_count", side_effect=boom):
                findings = detect_misplaced_product_tables(paths)
            kd = [f for f in findings if f.table == "knowledge_documents"]
            self.assertTrue(kd)
            self.assertEqual(kd[0].action, MISPLACED_BLOCK_UNKNOWN)

            report = reconcile_misplaced_product_tables(paths, apply=True)
            # Source must still exist — never dropped on UNKNOWN.
            con = sqlite3.connect(paths.control)
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            con.close()
            self.assertIn("knowledge_documents", tables)
            self.assertIn("knowledge_documents", report.blocked)
            self.assertFalse(report.completed)


class MisplacedMigrateVerifiedTests(unittest.TestCase):
    def test_migrate_copies_then_retires_only_after_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _init_empty_three(paths)
            # Seed canonical destination schema empty + misplaced source rows.
            k = sqlite3.connect(paths.knowledge)
            k.executescript(
                """
                CREATE TABLE knowledge_documents(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    source TEXT,
                    created_at TEXT
                );
                """
            )
            k.commit()
            k.close()
            c = sqlite3.connect(paths.control)
            c.executescript(
                """
                CREATE TABLE knowledge_documents(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    source TEXT,
                    created_at TEXT
                );
                INSERT INTO knowledge_documents(id, title, content)
                VALUES ('d1','T1','body');
                """
            )
            c.commit()
            c.close()

            findings = detect_misplaced_product_tables(paths)
            kd = next(f for f in findings if f.table == "knowledge_documents")
            self.assertEqual(kd.action, MISPLACED_MIGRATE)

            report = reconcile_misplaced_product_tables(paths, apply=True)
            self.assertIn("knowledge_documents", report.migrated)
            self.assertTrue(report.completed)

            k = sqlite3.connect(paths.knowledge)
            rows = k.execute("SELECT id, title FROM knowledge_documents").fetchall()
            k.close()
            self.assertEqual(rows, [("d1", "T1")])

            c = sqlite3.connect(paths.control)
            tables = {
                r[0]
                for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            c.close()
            self.assertNotIn("knowledge_documents", tables)

    def test_conflict_does_not_drop_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _init_empty_three(paths)
            ddl = """
                CREATE TABLE knowledge_documents(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT ''
                );
                """
            for path, title in ((paths.knowledge, "KEEP"), (paths.control, "OTHER")):
                con = sqlite3.connect(path)
                con.executescript(ddl)
                con.execute(
                    "INSERT INTO knowledge_documents(id, title) VALUES (?, ?)",
                    ("d1", title),
                )
                con.commit()
                con.close()

            report = reconcile_misplaced_product_tables(paths, apply=True)
            self.assertIn("knowledge_documents", report.blocked)
            self.assertFalse(report.completed)
            c = sqlite3.connect(paths.control)
            self.assertIn(
                "knowledge_documents",
                {
                    r[0]
                    for r in c.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                },
            )
            # Destination unchanged
            k = sqlite3.connect(paths.knowledge)
            self.assertEqual(
                k.execute("SELECT title FROM knowledge_documents").fetchone()[0],
                "KEEP",
            )
            k.close()
            c.close()

    def test_equivalent_retires_duplicate_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _init_empty_three(paths)
            ddl = """
                CREATE TABLE knowledge_documents(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO knowledge_documents(id, title, content)
                VALUES ('d1','T','x');
                """
            for path in (paths.knowledge, paths.control):
                con = sqlite3.connect(path)
                con.executescript(ddl)
                con.commit()
                con.close()

            report = reconcile_misplaced_product_tables(paths, apply=True)
            self.assertIn("knowledge_documents", report.retired_equivalent)
            self.assertTrue(report.completed)
            c = sqlite3.connect(paths.control)
            tables = {
                r[0]
                for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            c.close()
            self.assertNotIn("knowledge_documents", tables)

    def test_upgrade_report_not_complete_when_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Build a three-DB install via upgrade, then inject conflict.
            from Data.backend.db_upgrade import upgrade_all_databases

            paths = DatabasePaths(
                control=root / "leviathan_control.db",
                knowledge=root / "leviathan_knowledge.db",
                market=root / "leviathan_market.db",
            )
            first = upgrade_all_databases(paths)
            self.assertTrue(first.completed)

            # Inject conflicting misplaced table.
            ddl = """
                CREATE TABLE IF NOT EXISTS knowledge_documents(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT ''
                );
                """
            k = sqlite3.connect(paths.knowledge)
            k.executescript(ddl)
            k.execute(
                "INSERT OR IGNORE INTO knowledge_documents(id, title) VALUES ('x','K')"
            )
            k.commit()
            k.close()
            c = sqlite3.connect(paths.control)
            c.executescript(ddl)
            c.execute(
                "INSERT OR IGNORE INTO knowledge_documents(id, title) VALUES ('x','C')"
            )
            c.commit()
            c.close()

            second = upgrade_all_databases(paths)
            self.assertFalse(second.completed)
            self.assertTrue(second.errors)


if __name__ == "__main__":
    unittest.main()
