"""SQLite Manager API + three-DB cutover integration tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.db_upgrade import upgrade_all_databases
from Data.modules.common.database_domains import DatabasePaths
from Data.modules.sqlite_manager import SqliteManager, SqliteManagerError


class SqliteManagerThreeDbTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_sqlmgr_"))
        self.paths = DatabasePaths(
            control=root / "control.db",
            knowledge=root / "knowledge.db",
            market=root / "market.db",
        )
        report = upgrade_all_databases(self.paths)
        self.assertTrue(report.completed)
        self.manager = SqliteManager(self.paths)

    def test_list_and_status(self) -> None:
        dbs = self.manager.list_databases()
        self.assertEqual(len(dbs), 3)
        domains = {d["domain"] for d in dbs}
        self.assertEqual(domains, {"CONTROL", "KNOWLEDGE", "MARKET"})
        for d in dbs:
            self.assertTrue(d["exists"])
            self.assertGreaterEqual(d["schemaVersion"], 1)

    def test_read_write_each_domain(self) -> None:
        # CONTROL write
        self.manager.mutate(
            "CONTROL",
            "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
            "VALUES ('c1','t','2020-01-01','2020-01-01',0)",
            confirm_domain="CONTROL",
        )
        q = self.manager.query("CONTROL", "SELECT id FROM conversations")
        self.assertEqual(q["rows"], [["c1"]])

        # KNOWLEDGE write
        self.manager.mutate(
            "KNOWLEDGE",
            "INSERT INTO knowledge_documents(id,title,content,source,created_at,updated_at) "
            "VALUES ('k1','kd','body','manual','2020-01-01','2020-01-01')",
            confirm_domain="KNOWLEDGE",
        )
        q = self.manager.query("KNOWLEDGE", "SELECT id FROM knowledge_documents")
        self.assertEqual(q["rows"], [["k1"]])

        # Ensure no cross-DB bleed
        with self.assertRaises(SqliteManagerError):
            self.manager.query("CONTROL", "SELECT id FROM knowledge_documents")

        # MARKET write
        self.manager.mutate(
            "MARKET",
            "INSERT INTO market_strategies("
            "strategy_id, name, description, status, tags_json, current_version, "
            "content_hash, created_at, updated_at, metadata_json) "
            "VALUES ('s1','strat','','ACTIVE','[]',1,'h','2020-01-01','2020-01-01','{}')",
            confirm_domain="MARKET",
        )
        q = self.manager.query("MARKET", "SELECT strategy_id FROM market_strategies")
        self.assertEqual(q["rows"], [["s1"]])

    def test_confirm_domain_required(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.mutate(
                "KNOWLEDGE",
                "DELETE FROM knowledge_documents WHERE id='x'",
                confirm_domain="CONTROL",
            )
        self.assertEqual(ctx.exception.code, "DOMAIN_CONFIRM_MISMATCH")


if __name__ == "__main__":
    unittest.main()
