"""Wave 2 — three-database ownership constructor / worker path tests."""

from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.database import Database
from Data.backend.table_ownership import (
    CONTROL_TABLES,
    KNOWLEDGE_TABLES,
    MARKET_TABLES,
    ownership_for,
    validate_no_ambiguous_overlap,
)
from Data.modules.common.database_domains import (
    DatabaseDomain,
    resolve_control_database_path,
    resolve_knowledge_database_path,
    resolve_market_database_path,
)


class OwnershipMapTests(unittest.TestCase):
    def test_no_ambiguous_overlap(self) -> None:
        validate_no_ambiguous_overlap()

    def test_assimilation_receipts_are_control(self) -> None:
        self.assertEqual(
            ownership_for("intelligence_assimilation_receipts"),
            DatabaseDomain.CONTROL,
        )

    def test_market_checkpoints_are_market(self) -> None:
        self.assertEqual(
            ownership_for("market_feed_checkpoints"),
            DatabaseDomain.MARKET,
        )

    def test_source_ingestion_tables_are_knowledge(self) -> None:
        self.assertEqual(
            ownership_for("source_ingestion_containers"),
            DatabaseDomain.KNOWLEDGE,
        )


class ResolvePathHelpersTests(unittest.TestCase):
    def test_control_never_defaults_to_state_leviathan(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            # Clear deprecated alias if present
            import os

            os.environ.pop("LEVIATHAN_DB_PATH", None)
            path = resolve_control_database_path()
            self.assertNotIn("Data/state/leviathan.db", str(path).replace("\\", "/"))

    def test_distinct_domain_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "c.db"
            k = Path(tmp) / "k.db"
            m = Path(tmp) / "m.db"
            self.assertEqual(resolve_control_database_path(explicit=c), c)
            self.assertEqual(resolve_knowledge_database_path(explicit=k), k)
            self.assertEqual(resolve_market_database_path(explicit=m), m)


class LegacyDatabaseFacadeTests(unittest.TestCase):
    def test_initialize_does_not_create_knowledge_tables_on_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control.db"
            knowledge = Path(tmp) / "knowledge.db"
            db = Database(control, knowledge_path=knowledge)
            db.initialize()
            con = sqlite3.connect(control)
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            con.close()
            self.assertIn("conversations", tables)
            self.assertNotIn("knowledge_documents", tables)
            self.assertNotIn("knowledge_fts", tables)

    def test_knowledge_methods_write_to_knowledge_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control.db"
            knowledge = Path(tmp) / "knowledge.db"
            db = Database(control, knowledge_path=knowledge)
            db.initialize()
            db.upsert_knowledge(title="T", content="body about widgets", source="test")
            self.assertTrue(knowledge.exists())
            con = sqlite3.connect(knowledge)
            count = con.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0]
            con.close()
            self.assertEqual(count, 1)
            # CONTROL must remain free of knowledge product tables
            con = sqlite3.connect(control)
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            con.close()
            self.assertNotIn("knowledge_documents", tables)


class WorkerSourcePathAuditTests(unittest.TestCase):
    """Static proof that workers no longer bind KnowledgeStore to CONTROL compat path."""

    def test_research_worker_context_uses_knowledge_path(self) -> None:
        src = Path("Data/modules/research/worker_context.py").read_text(encoding="utf-8")
        self.assertIn("knowledge_database_path", src)
        self.assertIn("embedding_hash_dimensions", src)
        self.assertNotIn('getattr(settings.knowledge, "hash_dimensions"', src)

    def test_dataset_worker_uses_knowledge_path(self) -> None:
        src = Path("Data/modules/datasets/worker.py").read_text(encoding="utf-8")
        self.assertIn("knowledge_database_path", src)
        self.assertIn("embedding_hash_dimensions", src)
        self.assertNotIn("KnowledgeStore(\n        settings.database_path", src)

    def test_source_ingestion_worker_splits_domains(self) -> None:
        src = Path("Data/modules/source_ingestion/worker.py").read_text(encoding="utf-8")
        self.assertIn("knowledge_database_path", src)
        self.assertIn("ResearchStore(settings.database_path)", src)
        self.assertIn("database_path=settings.knowledge_database_path", src)

    def test_research_service_does_not_pass_control_to_ingestion(self) -> None:
        src = Path("Data/modules/research/service.py").read_text(encoding="utf-8")
        self.assertNotIn("database_path=store.db_path", src)
        self.assertIn("knowledge_database_path", src)

    def test_market_stream_resolves_market_db(self) -> None:
        src = Path("Data/modules/provider_io/adapters/market_stream.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("resolve_market_database_path", src)
        self.assertNotIn('os.environ.get("LEVIATHAN_DB_PATH")', src)

    def test_no_fourth_db_default_in_executors(self) -> None:
        for path in (
            "Data/modules/provider_io/executor.py",
            "Data/modules/provider_io/facade.py",
            "Data/modules/mcp/execution.py",
            "Data/modules/model_download/executor.py",
        ):
            src = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("Data/state/leviathan.db", src, msg=path)


class CanonicalPathDistinctTests(unittest.TestCase):
    def test_settings_paths_distinct(self) -> None:
        from Data.backend.config import load_settings

        s = load_settings()
        paths = {
            s.control_database_path.resolve(),
            s.knowledge_database_path.resolve(),
            s.market_database_path.resolve(),
        }
        self.assertEqual(len(paths), 3)


if __name__ == "__main__":
    unittest.main()
