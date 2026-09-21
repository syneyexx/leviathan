"""T8/F-14+F-15: atomic knowledge ingest and retention pruning."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from platform_db import PlatformDatabase
from platform_services_core import KnowledgeService
from retention import (
    cutoff_iso,
    prune_core_tables,
    prune_platform_tables,
    resolve_retention_days,
    run_retention_job,
)


class AtomicKnowledgeIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "platform.db"))
        self.db.initialize()
        self.knowledge = KnowledgeService(self.db, self.root / "data")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_with_chunks_is_single_transaction(self) -> None:
        source = self.db.upsert_knowledge_with_chunks(
            title="Doc",
            source_type="note",
            uri="note://atomic-1",
            chunks=[{"content": "Hello atomic world.", "heading": "H1"}],
            content_hash="abc",
            status="ready",
        )
        self.assertEqual(source.get("status"), "ready")
        chunks = self.db.list_knowledge_chunks(source["id"])
        self.assertEqual(len(chunks), 1)

    def test_empty_chunks_do_not_publish_ready_source(self) -> None:
        source = self.db.upsert_knowledge_with_chunks(
            title="Empty",
            source_type="note",
            uri="note://empty-1",
            chunks=[{"content": "   "}],
            content_hash="empty",
            status="ready",
        )
        self.assertEqual(source.get("status"), "verification_failed")
        self.assertEqual(int(source.get("chunks_written") or 0), 0)

    def test_crash_between_source_and_chunks_cannot_leave_ready_zero(self) -> None:
        """Simulate failure after pending source write by injecting into replace."""
        calls = {"n": 0}
        real_replace = self.db._replace_knowledge_chunks_conn

        def boom(db, source_id, title, chunks, *, now=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated_crash_mid_ingest")
            return real_replace(db, source_id, title, chunks, now=now)

        with mock.patch.object(self.db, "_replace_knowledge_chunks_conn", side_effect=boom):
            with self.assertRaises(RuntimeError):
                self.db.upsert_knowledge_with_chunks(
                    title="Crash",
                    source_type="note",
                    uri="note://crash-1",
                    chunks=[{"content": "should roll back"}],
                    content_hash="x",
                    status="ready",
                )
        # Transaction rolled back: either no source, or not ready with chunks.
        row = self.db.get_knowledge_source_by_uri("note", "note://crash-1")
        if row is not None:
            self.assertNotEqual(row.get("status"), "ready")
            self.assertEqual(len(self.db.list_knowledge_chunks(row["id"])), 0)

    def test_ingest_text_uses_atomic_path(self) -> None:
        result = self.knowledge.ingest_text(
            title="Note",
            text="Paragraph one.\n\nParagraph two is longer.",
            source_type="note",
            uri="note://ingest-1",
        )
        self.assertEqual(result.get("status"), "ready")
        self.assertGreater(int(result.get("chunks") or 0), 0)
        source = self.db.get_knowledge_source(result["id"])
        self.assertEqual(source.get("status"), "ready")


class RetentionJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        from database import Database

        self.core = Database(str(self.root / "hades.db"))
        self.core.initialize()
        self.platform = PlatformDatabase(str(self.root / "hades.db"))
        self.platform.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_retention_days(self) -> None:
        self.assertIsNone(resolve_retention_days({}))
        self.assertIsNone(resolve_retention_days({"log_retention_days": 0}))
        self.assertEqual(resolve_retention_days({"log_retention_days": 7}), 7)
        self.assertEqual(resolve_retention_days({"logging.retention_days": 14}), 14)

    def test_prune_deletes_old_and_keeps_recent(self) -> None:
        now = datetime(2026, 9, 18, tzinfo=UTC)
        old = (now - timedelta(days=40)).isoformat(timespec="seconds")
        recent = (now - timedelta(days=2)).isoformat(timespec="seconds")
        with self.core.connection() as db:
            db.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                ("c1", "t", recent, recent),
            )
            db.execute(
                "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)",
                ("m_old", "c1", "user", "old", old),
            )
            db.execute(
                "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)",
                ("m_new", "c1", "user", "new", recent),
            )
            db.execute(
                "INSERT INTO tasks(id,title,prompt,agent,priority,status,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                ("t1", "T", "p", "auto", "normal", "completed", 100, recent, recent),
            )
            db.execute(
                "INSERT INTO task_events(task_id,level,message,created_at) VALUES(?,?,?,?)",
                ("t1", "info", "old event", old),
            )
            db.execute(
                "INSERT INTO task_events(task_id,level,message,created_at) VALUES(?,?,?,?)",
                ("t1", "info", "new event", recent),
            )
        with self.platform.connection() as db:
            db.execute(
                "INSERT INTO research_projects(id,title,topic,depth,status,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                ("rp1", "R", "topic", "standard", "completed", 100, recent, recent),
            )
            db.execute(
                "INSERT INTO research_events(project_id,level,message,created_at) VALUES(?,?,?,?)",
                ("rp1", "info", "old", old),
            )
            db.execute(
                "INSERT INTO research_events(project_id,level,message,created_at) VALUES(?,?,?,?)",
                ("rp1", "info", "new", recent),
            )
            db.execute(
                """INSERT INTO agent_usage_events
                   (id,agent_id,provider,created_at) VALUES(?,?,?,?)""",
                ("u_old", "critic", "lm_studio", old),
            )
            db.execute(
                """INSERT INTO tool_calls
                   (id,plugin_id,tool_name,input_json,status,started_at,finished_at)
                   VALUES(?,?,?,?,?,?,?)""",
                ("tc_old", "p", "echo", "{}", "completed", old, old),
            )

        result = run_retention_job(
            database=self.core,
            platform_db=self.platform,
            settings={"log_retention_days": 30},
            now=now,
        )
        self.assertFalse(result["skipped"])
        self.assertGreaterEqual(result["deleted"]["messages"], 1)
        self.assertGreaterEqual(result["deleted"]["task_events"], 1)
        self.assertGreaterEqual(result["deleted"]["research_events"], 1)
        with self.core.connection() as db:
            ids = {row["id"] for row in db.execute("SELECT id FROM messages").fetchall()}
            self.assertIn("m_new", ids)
            self.assertNotIn("m_old", ids)
        with self.platform.connection() as db:
            msgs = [row["message"] for row in db.execute("SELECT message FROM research_events").fetchall()]
            self.assertIn("new", msgs)
            self.assertNotIn("old", msgs)

    def test_unset_retention_skips(self) -> None:
        result = run_retention_job(
            database=self.core,
            platform_db=self.platform,
            settings={},
        )
        self.assertTrue(result["skipped"])

    def test_research_events_index_exists(self) -> None:
        with self.platform.connection() as db:
            rows = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_research_events_project'"
            ).fetchall()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
