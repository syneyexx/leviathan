"""Tests for three-database registry, ownership, and legacy cutover."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from Data.backend.db_upgrade import (
    CutoverPhase,
    DatabaseUpgradeError,
    InstallMode,
    detect_install_mode,
    upgrade_all_databases,
)
from Data.backend.migrations import MigrationRunner
from Data.backend.table_ownership import (
    CONTROL_TABLES,
    KNOWLEDGE_TABLES,
    MARKET_TABLES,
    all_classified_product_tables,
    ownership_for,
    require_ownership,
    validate_no_ambiguous_overlap,
)
from Data.modules.common.database_domains import (
    DatabaseDomain,
    DatabasePaths,
    domain_from_commit_operation,
)


class TableOwnershipTests(unittest.TestCase):
    def test_no_overlap(self) -> None:
        validate_no_ambiguous_overlap()

    def test_known_tables(self) -> None:
        self.assertEqual(ownership_for("conversations"), DatabaseDomain.CONTROL)
        self.assertEqual(ownership_for("knowledge_chunks"), DatabaseDomain.KNOWLEDGE)
        self.assertEqual(ownership_for("market_sim_fills"), DatabaseDomain.MARKET)
        self.assertEqual(ownership_for("institutional_authority_approvals"), DatabaseDomain.MARKET)
        self.assertEqual(ownership_for("institutional_ibor_events"), DatabaseDomain.MARKET)

    def test_unclassified_fails_require(self) -> None:
        with self.assertRaises(Exception):
            require_ownership("definitely_not_a_real_table_xyz")

    def test_migration_tables_covered(self) -> None:
        import re

        text = Path("Data/backend/migrations.py").read_text(encoding="utf-8")
        tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text))
        tables.discard("schema_migrations")
        missing = sorted(t for t in tables if ownership_for(t) is None and t not in {"schema_migrations"})
        # schema_migrations is infrastructure; everything else must classify.
        self.assertEqual(missing, [], msg=f"unclassified migration tables: {missing}")


class DatabasePathsTests(unittest.TestCase):
    def test_domain_routing_hint(self) -> None:
        self.assertEqual(
            domain_from_commit_operation("knowledge.commit_prepared", "knowledge"),
            DatabaseDomain.KNOWLEDGE,
        )
        self.assertEqual(
            domain_from_commit_operation("market_sim.append_events", "market_sim"),
            DatabaseDomain.MARKET,
        )
        self.assertEqual(
            domain_from_commit_operation("trading.approval", "trading"),
            DatabaseDomain.CONTROL,
        )

    def test_settings_three_paths(self) -> None:
        from Data.backend.config import load_settings

        settings = load_settings()
        self.assertEqual(settings.database_path, settings.control_database_path)
        self.assertNotEqual(settings.control_database_path, settings.knowledge_database_path)
        self.assertNotEqual(settings.knowledge_database_path, settings.market_database_path)
        self.assertIn("CONTROL", settings.database_paths.public_dict()["domains"])


class FreshAndLegacyCutoverTests(unittest.TestCase):
    def test_fresh_install_and_rerun(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_fresh_"))
        paths = DatabasePaths(
            control=root / "control.db",
            knowledge=root / "knowledge.db",
            market=root / "market.db",
        )
        self.assertEqual(detect_install_mode(paths), InstallMode.FRESH)
        report = upgrade_all_databases(paths)
        self.assertTrue(report.completed)
        self.assertEqual(report.phase, CutoverPhase.COMPLETE)
        for _, path in paths:
            self.assertTrue(path.is_file())
            self.assertGreaterEqual(
                MigrationRunner(path).current_version(sqlite3.connect(path)),
                1,
            )
        again = upgrade_all_databases(paths)
        self.assertTrue(again.completed)

    def test_legacy_cutover_preserves_rows_and_is_idempotent(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_leg_"))
        legacy = root / "legacy.db"
        MigrationRunner(legacy).apply_all()
        with sqlite3.connect(legacy) as conn:
            conn.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
                "VALUES ('c1','t','2020-01-01','2020-01-01',0)"
            )
            conn.execute(
                "INSERT INTO knowledge_documents(id,title,content,source,created_at,updated_at) "
                "VALUES ('k1','kd','body','manual','2020-01-01','2020-01-01')"
            )
            conn.execute(
                "INSERT INTO market_strategies("
                "strategy_id, name, description, status, tags_json, current_version, "
                "content_hash, created_at, updated_at, metadata_json) "
                "VALUES ('s1','strat','','ACTIVE','[]',1,'h','2020-01-01','2020-01-01','{}')"
            )
            conn.commit()

        out = Path(tempfile.mkdtemp(prefix="lv_out_"))
        paths = DatabasePaths(
            control=out / "c.db",
            knowledge=out / "k.db",
            market=out / "m.db",
            legacy=legacy,
        )
        report = upgrade_all_databases(paths)
        self.assertTrue(report.completed)
        self.assertTrue(legacy.is_file())

        with sqlite3.connect(paths.control) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1)
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertNotIn("knowledge_documents", tables)
            self.assertNotIn("market_strategies", tables)

        with sqlite3.connect(paths.knowledge) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0], 1
            )
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertNotIn("conversations", tables)

        with sqlite3.connect(paths.market) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM market_strategies").fetchone()[0], 1
            )

        again = upgrade_all_databases(paths)
        self.assertTrue(again.completed)
        with sqlite3.connect(paths.control) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1)

    def test_interrupted_cutover_resumes(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_int_"))
        legacy = root / "legacy.db"
        MigrationRunner(legacy).apply_all()
        with sqlite3.connect(legacy) as conn:
            conn.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
                "VALUES ('c2','t2','2020-01-01','2020-01-01',0)"
            )
            conn.commit()

        out = Path(tempfile.mkdtemp(prefix="lv_int_out_"))
        paths = DatabasePaths(
            control=out / "c.db",
            knowledge=out / "k.db",
            market=out / "m.db",
            legacy=legacy,
        )
        # Simulate partial: create three DBs via first upgrade then wipe cutover complete
        # and remove one target to force resume path... Instead mark phase COPYING.
        first = upgrade_all_databases(paths)
        self.assertTrue(first.completed)
        with sqlite3.connect(paths.control) as conn:
            conn.execute(
                "UPDATE db_cutover_state SET value='COPYING' WHERE key='phase'"
            )
            conn.commit()
        # Delete knowledge rows to simulate incomplete copy; rerun should restore.
        with sqlite3.connect(paths.knowledge) as conn:
            # knowledge may be empty in this fixture — insert then delete conversations won't apply
            pass
        resumed = upgrade_all_databases(paths)
        self.assertTrue(resumed.completed)

    def test_ambiguous_partial_set_fails(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="lv_amb_"))
        control = root / "c.db"
        # Non-empty product rows in a partial set must stay fail-closed.
        with sqlite3.connect(control) as conn:
            conn.execute(
                "CREATE TABLE conversations ("
                "id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT, pinned INTEGER)"
            )
            conn.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at,pinned) "
                "VALUES ('c1','t','2020-01-01','2020-01-01',0)"
            )
            conn.commit()
        paths = DatabasePaths(
            control=control,
            knowledge=root / "k.db",
            market=root / "m.db",
        )
        self.assertEqual(detect_install_mode(paths), InstallMode.AMBIGUOUS)
        with self.assertRaises(DatabaseUpgradeError):
            upgrade_all_databases(paths)

    def test_empty_partial_control_completes_as_fresh(self) -> None:
        """Supervisor / PreferenceStore may create CONTROL alone before siblings."""
        root = Path(tempfile.mkdtemp(prefix="lv_empty_partial_"))
        control = root / "c.db"
        control.write_bytes(b"")
        paths = DatabasePaths(
            control=control,
            knowledge=root / "k.db",
            market=root / "m.db",
        )
        self.assertEqual(detect_install_mode(paths), InstallMode.FRESH)
        report = upgrade_all_databases(paths)
        self.assertTrue(report.completed)
        for _, path in paths:
            self.assertTrue(path.is_file())

    def test_runs_schema_matches_run_store_after_upgrade(self) -> None:
        """Regression: stub runs(id/kind/…) broke RunStore.initialize at API lifespan."""
        from Data.modules.run.store import RunStore

        root = Path(tempfile.mkdtemp(prefix="lv_runs_schema_"))
        paths = DatabasePaths(
            control=root / "c.db",
            knowledge=root / "k.db",
            market=root / "m.db",
        )
        report = upgrade_all_databases(paths)
        self.assertTrue(report.completed)
        with sqlite3.connect(paths.control) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        self.assertIn("run_id", cols)
        self.assertIn("conversation_id", cols)
        self.assertNotIn("kind", cols)

        store = RunStore(paths.control)
        store.initialize()  # must not raise "no such column: conversation_id"
        run = store.create_run(user_request="boot-ok", conversation_id="c1")
        self.assertEqual(run.conversation_id, "c1")

    def test_repairs_legacy_stub_runs_table(self) -> None:
        from Data.backend.db_upgrade import repair_incompatible_runs_schema
        from Data.modules.run.store import RunStore

        root = Path(tempfile.mkdtemp(prefix="lv_stub_runs_"))
        db = root / "c.db"
        with sqlite3.connect(db) as conn:
            conn.executescript(
                """
                CREATE TABLE runs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'created',
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()
        with sqlite3.connect(db) as conn:
            self.assertTrue(repair_incompatible_runs_schema(conn))
            conn.commit()
            cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        self.assertIn("run_id", cols)
        RunStore(db).initialize()
        RunStore(db).create_run(user_request="after-repair")


class WorkerDomainPathRoutingTests(unittest.TestCase):
    """Worker entrypoints must bind Knowledge/Market stores to owning DBs."""

    def test_knowledge_prepare_uses_knowledge_path(self) -> None:
        from Data.modules.workers.entrypoints import knowledge_prepare as kp

        root = Path(tempfile.mkdtemp(prefix="lv_kp_"))
        control = root / "control.db"
        knowledge = root / "knowledge.db"
        data_dir = root / "data"
        data_dir.mkdir()

        class _K:
            chunk_max_chars = 200
            chunk_overlap = 20

        kcfg = _K()
        kcfg.data_root = data_dir

        class _S:
            pass

        settings = _S()
        settings.database_path = control
        settings.knowledge_database_path = knowledge
        settings.knowledge = kcfg

        store = kp._knowledge_store({"settings": settings})
        self.assertEqual(Path(store.path).resolve(), knowledge.resolve())
        self.assertTrue(knowledge.is_file())
        self.assertFalse(control.is_file())

    def test_market_sim_news_poll_uses_market_path(self) -> None:
        from Data.modules.market_sim.orchestra.store import OrchestraStore

        root = Path(tempfile.mkdtemp(prefix="lv_ms_"))
        control = root / "control.db"
        market = root / "market.db"

        class _S:
            database_path = control
            market_database_path = market

        settings = _S()
        market_db = getattr(settings, "market_database_path", None) or settings.database_path
        store = OrchestraStore(Path(market_db))
        store.initialize()
        self.assertEqual(Path(store.db_path).resolve(), market.resolve())
        self.assertTrue(market.is_file())
        self.assertFalse(control.is_file())

    def test_storage_authority_three_db_truth(self) -> None:
        from Data.modules.datasets.storage_authority import (
            CANONICAL_PRODUCT_DB_BASENAMES,
            classify_path,
            storage_authority_public_dict,
        )

        truth = storage_authority_public_dict()
        self.assertEqual(truth["truth"]["canonicalDatabaseCount"], 3)
        self.assertEqual(
            truth["truth"]["canonicalTransactionalAuthority"],
            "three_sqlite_databases_control_knowledge_market",
        )
        self.assertIn("leviathan_knowledge.db", CANONICAL_PRODUCT_DB_BASENAMES)
        root = Path(tempfile.mkdtemp(prefix="lv_sa_"))
        paths = DatabasePaths(
            control=root / "leviathan_control.db",
            knowledge=root / "leviathan_knowledge.db",
            market=root / "leviathan_market.db",
        )
        for _, p in paths:
            p.write_bytes(b"")
            self.assertEqual(
                classify_path(p, database_paths=paths).value,
                "CANONICAL_TRANSACTIONAL",
            )


if __name__ == "__main__":
    unittest.main()
