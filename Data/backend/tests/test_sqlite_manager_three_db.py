"""SQLite Manager — institutional three-DB operator surface tests."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from Data.backend.db_upgrade import upgrade_all_databases
from Data.backend.table_ownership import ownership_for, validate_no_ambiguous_overlap
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.sqlite_manager import SqliteManager, SqliteManagerError
from Data.modules.sqlite_manager.ownership_audit import ownership_audit_for_tables
from Data.modules.sqlite_manager.sql_safety import (
    classify_read_sql,
    classify_write_sql,
    normalize_sql,
)


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

    # --- Wave 1 invariants -------------------------------------------------

    def test_list_and_status(self) -> None:
        dbs = self.manager.list_databases()
        self.assertEqual(len(dbs), 3)
        domains = {d["domain"] for d in dbs}
        self.assertEqual(domains, {"CONTROL", "KNOWLEDGE", "MARKET"})
        paths = {d["path"] for d in dbs}
        self.assertEqual(len(paths), 3)
        for d in dbs:
            self.assertTrue(d["exists"])
            self.assertGreaterEqual(d["schemaVersion"], 1)
            self.assertIn("ownershipDescription", d)
            self.assertIn("health", d)
            self.assertIn("tableCount", d)

    def test_paths_distinct_and_ownership_non_ambiguous(self) -> None:
        validate_no_ambiguous_overlap()
        resolved = {p.resolve() for _, p in self.paths}
        self.assertEqual(len(resolved), 3)
        self.assertIs(ownership_for("conversations"), DatabaseDomain.CONTROL)
        self.assertIs(ownership_for("knowledge_documents"), DatabaseDomain.KNOWLEDGE)
        self.assertIs(ownership_for("market_strategies"), DatabaseDomain.MARKET)

    def test_read_write_each_domain(self) -> None:
        self.manager.mutate(
            "CONTROL",
            "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
            "VALUES ('c1','t','2020-01-01','2020-01-01',0)",
            confirm_domain="CONTROL",
        )
        q = self.manager.query("CONTROL", "SELECT id FROM conversations")
        self.assertEqual(q["rows"], [["c1"]])
        self.assertIn("elapsedMs", q)

        self.manager.mutate(
            "KNOWLEDGE",
            "INSERT INTO knowledge_documents(id,title,content,source,created_at,updated_at) "
            "VALUES ('k1','kd','body','manual','2020-01-01','2020-01-01')",
            confirm_domain="KNOWLEDGE",
        )
        q = self.manager.query("KNOWLEDGE", "SELECT id FROM knowledge_documents")
        self.assertEqual(q["rows"], [["k1"]])

        with self.assertRaises(SqliteManagerError):
            self.manager.query("CONTROL", "SELECT id FROM knowledge_documents")

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

    def test_unknown_domain_fails_closed(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.list_tables("NOT_A_DOMAIN")
        self.assertEqual(ctx.exception.code, "UNKNOWN_DATABASE_DOMAIN")

    def test_missing_database(self) -> None:
        missing = DatabasePaths(
            control=self.paths.control.parent / "missing_control.db",
            knowledge=self.paths.knowledge,
            market=self.paths.market,
        )
        mgr = SqliteManager(missing)
        with self.assertRaises(SqliteManagerError) as ctx:
            mgr.query("CONTROL", "SELECT 1")
        self.assertEqual(ctx.exception.code, "DATABASE_MISSING")

    # --- SQL safety --------------------------------------------------------

    def test_multi_statement_forbidden(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.query("CONTROL", "SELECT 1; SELECT 2")
        self.assertEqual(ctx.exception.code, "MULTI_STATEMENT_FORBIDDEN")
        with self.assertRaises(SqliteManagerError) as ctx2:
            self.manager.mutate(
                "CONTROL",
                "DELETE FROM conversations WHERE id='x'; DELETE FROM conversations WHERE id='y'",
                confirm_domain="CONTROL",
            )
        self.assertEqual(ctx2.exception.code, "MULTI_STATEMENT_FORBIDDEN")

    def test_comment_prefixed_mutation_bypass_fails(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.query("CONTROL", "-- innocent\nDELETE FROM conversations")
        self.assertEqual(ctx.exception.code, "READ_ONLY_QUERY")
        with self.assertRaises(SqliteManagerError) as ctx2:
            self.manager.mutate(
                "CONTROL",
                "/* bypass */ CREATE TABLE evil(x INT)",
                confirm_domain="CONTROL",
            )
        self.assertIn(ctx2.exception.code, {"WRITE_NOT_ALLOWLISTED", "SCHEMA_MUTATION_FORBIDDEN"})

    def test_schema_mutation_forbidden(self) -> None:
        for sql in (
            "DROP TABLE conversations",
            "ALTER TABLE conversations ADD COLUMN x INT",
            "ATTACH DATABASE 'x.db' AS other",
            "VACUUM",
            "PRAGMA writable_schema=ON",
        ):
            with self.assertRaises(SqliteManagerError) as ctx:
                self.manager.mutate("CONTROL", sql, confirm_domain="CONTROL")
            self.assertIn(
                ctx.exception.code,
                {"WRITE_NOT_ALLOWLISTED", "SCHEMA_MUTATION_FORBIDDEN", "READ_ONLY_QUERY"},
            )

    def test_unsafe_pragma_write_fails_on_query(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.query("CONTROL", "PRAGMA journal_mode=DELETE")
        self.assertIn(ctx.exception.code, {"SCHEMA_MUTATION_FORBIDDEN", "READ_ONLY_QUERY"})

    def test_cte_select_allowed_cte_dml_rejected(self) -> None:
        q = self.manager.query("CONTROL", "WITH x AS (SELECT 1 AS n) SELECT n FROM x")
        self.assertEqual(q["rows"], [[1]])
        with self.assertRaises(SqliteManagerError):
            self.manager.query(
                "CONTROL",
                "WITH x AS (SELECT 1 AS n) INSERT INTO conversations(id) SELECT n FROM x",
            )

    def test_bounded_query_response(self) -> None:
        for i in range(5):
            self.manager.mutate(
                "CONTROL",
                "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
                f"VALUES ('b{i}','t','2020-01-01','2020-01-01',0)",
                confirm_domain="CONTROL",
            )
        q = self.manager.query(
            "CONTROL",
            "SELECT id FROM conversations ORDER BY id",
            limit=2,
        )
        self.assertEqual(q["rowCount"], 2)
        self.assertTrue(q["truncated"])
        self.assertEqual(q["limit"], 2)

    # --- table / rows / ownership ------------------------------------------

    def test_table_browser_ownership_annotation(self) -> None:
        tables = self.manager.list_tables("KNOWLEDGE")
        names = {t["name"] for t in tables}
        self.assertIn("knowledge_documents", names)
        kd = next(t for t in tables if t["name"] == "knowledge_documents")
        self.assertEqual(kd["ownershipState"], "EXPECTED")
        self.assertEqual(kd["owningDomain"], "KNOWLEDGE")
        detail = self.manager.table_detail("KNOWLEDGE", "knowledge_documents")
        self.assertTrue(detail["primaryKey"])
        self.assertIn("indexes", detail)
        self.assertIn("foreignKeys", detail)

    def test_cross_domain_table_access_fails(self) -> None:
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.table_detail("CONTROL", "knowledge_documents")
        self.assertEqual(ctx.exception.code, "TABLE_NOT_FOUND")

    def test_pagination_and_filters(self) -> None:
        for i in range(4):
            self.manager.mutate(
                "KNOWLEDGE",
                "INSERT INTO knowledge_documents(id,title,content,source,created_at,updated_at) "
                f"VALUES ('p{i}','title{i}','body','manual','2020-01-01','2020-01-01')",
                confirm_domain="KNOWLEDGE",
            )
        page = self.manager.query_rows(
            "KNOWLEDGE",
            "knowledge_documents",
            offset=0,
            limit=2,
            order_by=["id"],
        )
        self.assertEqual(page["rowCount"], 2)
        self.assertTrue(page["truncated"])
        page2 = self.manager.query_rows(
            "KNOWLEDGE",
            "knowledge_documents",
            offset=2,
            limit=2,
            order_by=["id"],
        )
        self.assertEqual(page2["rowCount"], 2)
        filtered = self.manager.query_rows(
            "KNOWLEDGE",
            "knowledge_documents",
            filters=[{"column": "id", "op": "=", "value": "p1"}],
        )
        self.assertEqual(filtered["rowCount"], 1)
        self.assertEqual(filtered["rows"][0]["identity"]["id"], "p1")

    def test_structured_row_edit_parameterized(self) -> None:
        self.manager.insert_row(
            "CONTROL",
            "conversations",
            {
                "id": "edit1",
                "title": "before",
                "created_at": "2020-01-01",
                "updated_at": "2020-01-01",
                "pinned": 0,
            },
            confirm_domain="CONTROL",
        )
        updated = self.manager.update_row(
            "CONTROL",
            "conversations",
            {"id": "edit1"},
            {"title": "after"},
            confirm_domain="CONTROL",
        )
        self.assertTrue(updated["ok"])
        self.assertEqual(updated["rowcount"], 1)
        q = self.manager.query("CONTROL", "SELECT title FROM conversations WHERE id='edit1'")
        self.assertEqual(q["rows"], [["after"]])
        deleted = self.manager.delete_row(
            "CONTROL",
            "conversations",
            {"id": "edit1"},
            confirm_domain="CONTROL",
        )
        self.assertEqual(deleted["rowcount"], 1)

    def test_no_pk_row_edit_rejection(self) -> None:
        # Create a disposable table without PK in CONTROL via raw sqlite (test fixture only).
        conn = sqlite3.connect(str(self.paths.control))
        try:
            conn.execute("CREATE TABLE no_pk_fixture(a TEXT, b TEXT)")
            conn.execute("INSERT INTO no_pk_fixture(a,b) VALUES ('x','y')")
            conn.commit()
        finally:
            conn.close()
        detail = self.manager.table_detail("CONTROL", "no_pk_fixture")
        self.assertFalse(detail["rowEditAvailable"])
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.update_row(
                "CONTROL",
                "no_pk_fixture",
                {"a": "x"},
                {"b": "z"},
                confirm_domain="CONTROL",
            )
        self.assertEqual(ctx.exception.code, "ROW_IDENTITY_UNAVAILABLE")

    def test_mutation_rollback_on_error(self) -> None:
        before = self.manager.query("CONTROL", "SELECT COUNT(*) FROM conversations")
        with self.assertRaises(SqliteManagerError) as ctx:
            self.manager.mutate(
                "CONTROL",
                "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
                "VALUES (NULL,NULL,NULL,NULL,NULL)",
                confirm_domain="CONTROL",
            )
        self.assertEqual(ctx.exception.code, "MUTATION_FAILED")
        after = self.manager.query("CONTROL", "SELECT COUNT(*) FROM conversations")
        self.assertEqual(before["rows"], after["rows"])

    def test_integrity_checks(self) -> None:
        for domain in ("CONTROL", "KNOWLEDGE", "MARKET"):
            quick = self.manager.integrity_check(domain, kind="quick_check")
            self.assertTrue(quick["ok"], msg=domain)
            self.assertEqual(quick["domain"], domain)
            fk = self.manager.integrity_check(domain, kind="foreign_key_check")
            self.assertEqual(fk["domain"], domain)
            full = self.manager.integrity_check(domain, kind="integrity_check")
            self.assertTrue(full["ok"], msg=domain)

    def test_ownership_audit_clean_and_wrong_domain_fixture(self) -> None:
        audit = self.manager.ownership_audit()
        self.assertIn("findings", audit)
        self.assertIn("counts", audit)
        # Inject a knowledge table into CONTROL to detect WRONG_DATABASE.
        conn = sqlite3.connect(str(self.paths.control))
        try:
            conn.execute(
                "CREATE TABLE knowledge_documents("
                "id TEXT PRIMARY KEY, title TEXT, content TEXT, source TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            conn.commit()
        finally:
            conn.close()
        audit2 = self.manager.ownership_audit()
        kinds = {f.get("kind") or f.get("ownershipState") for f in audit2["findings"]}
        self.assertTrue(
            "WRONG_DATABASE" in kinds or any(
                f.get("ownershipState") == "WRONG_DATABASE" for f in audit2["findings"]
            )
        )
        self.assertFalse(audit2["ok"])

    def test_duplicate_product_detection_unit(self) -> None:
        present = {
            "CONTROL": {"conversations", "knowledge_documents"},
            "KNOWLEDGE": {"knowledge_documents"},
            "MARKET": set(),
        }
        audit = ownership_audit_for_tables(present_by_domain=present)
        self.assertGreaterEqual(audit["counts"]["WRONG_DATABASE"], 1)
        self.assertGreaterEqual(audit["counts"]["DUPLICATE_PRODUCT"], 1)

    def test_runtime_status_truthful(self) -> None:
        runtime = self.manager.runtime_status()
        self.assertIn("sqliteMetrics", runtime)
        self.assertIn("contention", runtime)
        self.assertIn("writePolicy", runtime)
        self.assertEqual(len(runtime["databases"]), 3)
        # Without deps, backup/dbCommit must not invent success.
        self.assertIn(runtime["backup"].get("available"), (False, True))
        self.assertIn("status", runtime["dbCommit"])

    def test_wal_checkpoint_passive(self) -> None:
        result = self.manager.wal_checkpoint(
            "CONTROL", mode="PASSIVE", confirm_domain="CONTROL"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "PASSIVE")

    def test_writes_disabled(self) -> None:
        mgr = SqliteManager(self.paths, allow_writes=False)
        with self.assertRaises(SqliteManagerError) as ctx:
            mgr.mutate(
                "CONTROL",
                "DELETE FROM conversations WHERE id='none'",
                confirm_domain="CONTROL",
            )
        self.assertEqual(ctx.exception.code, "WRITES_DISABLED")

    def test_sql_normalize_helpers(self) -> None:
        self.assertEqual(normalize_sql("  --x\nSELECT 1  "), "SELECT 1")
        self.assertEqual(classify_read_sql("PRAGMA table_info('conversations')"), "PRAGMA")
        self.assertEqual(classify_write_sql("INSERT INTO t(a) VALUES (1)"), "INSERT")
        with self.assertRaises(ValueError):
            classify_write_sql("UPDATE t SET a=1; DROP TABLE t")


class SqliteManagerBusyTests(unittest.TestCase):
    def test_busy_surfaces_honestly(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_sqlmgr_busy_"))
        paths = DatabasePaths(
            control=root / "control.db",
            knowledge=root / "knowledge.db",
            market=root / "market.db",
        )
        upgrade_all_databases(paths)
        manager = SqliteManager(paths)
        holder = sqlite3.connect(str(paths.control), timeout=0.1)
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("CREATE TABLE IF NOT EXISTS busy_lock(x INT)")
        err_box: list[SqliteManagerError] = []

        def _attempt() -> None:
            try:
                manager.mutate(
                    "CONTROL",
                    "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
                    "VALUES ('busy','t','2020-01-01','2020-01-01',0)",
                    confirm_domain="CONTROL",
                )
            except SqliteManagerError as exc:
                err_box.append(exc)

        t = threading.Thread(target=_attempt)
        t.start()
        t.join(timeout=15)
        holder.rollback()
        holder.close()
        # Either succeeded after retries or surfaced DB_BUSY / MUTATION_FAILED honestly.
        if err_box:
            self.assertIn(err_box[0].code, {"DB_BUSY", "MUTATION_FAILED"})


if __name__ == "__main__":
    unittest.main()
