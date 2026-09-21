"""HADES-10 Phase 3A: conversation ↔ run binding persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conversation_runs import (
    TERMINAL_STATUSES,
    bind_conversation_run,
    list_conversation_runs,
    update_conversation_run_status,
)
from database import Database
from platform_db import PlatformDatabase


class ConversationRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = Database(str(root / "hades.db"))
        self.db.initialize()
        self.platform = PlatformDatabase(str(root / "hades.db"))
        self.platform.initialize()
        self.conversation = self.db.create_conversation(title="Phase 3A")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bind_list_update_idempotent(self) -> None:
        cid = self.conversation["id"]
        first = bind_conversation_run(
            self.platform,
            conversation_id=cid,
            run_id="cjob_abc",
            run_type="coding",
            status="running",
            title="Fix bug",
            metadata={"workspace": "C:/repo"},
        )
        self.assertEqual(first["run_id"], "cjob_abc")
        self.assertEqual(first["run_type"], "coding")
        self.assertEqual(first["status"], "running")

        again = bind_conversation_run(
            self.platform,
            conversation_id=cid,
            run_id="cjob_abc",
            run_type="coding",
            status="running",
            title="Fix bug",
        )
        self.assertEqual(again["id"], first["id"])

        bind_conversation_run(
            self.platform,
            conversation_id=cid,
            run_id="research_1",
            run_type="research",
            status="running",
        )
        rows = list_conversation_runs(self.platform, cid)
        self.assertEqual(len(rows), 2)

        active = list_conversation_runs(self.platform, cid, active_only=True)
        self.assertEqual(len(active), 2)

        updated = update_conversation_run_status(
            self.platform,
            conversation_id=cid,
            run_id="cjob_abc",
            status="completed",
            metadata={"tests_passed": True},
        )
        assert updated is not None
        self.assertEqual(updated["status"], "completed")
        self.assertTrue(updated["metadata"].get("tests_passed"))
        self.assertIn(updated["status"], TERMINAL_STATUSES)

        active_after = list_conversation_runs(self.platform, cid, active_only=True)
        self.assertEqual(len(active_after), 1)
        self.assertEqual(active_after[0]["run_type"], "research")

    def test_migration_creates_table(self) -> None:
        with self.platform.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=17"
            ).fetchone()
            self.assertIsNotNone(row)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(conversation_runs)").fetchall()}
        self.assertIn("conversation_id", cols)
        self.assertIn("run_id", cols)
        self.assertIn("run_type", cols)


if __name__ == "__main__":
    unittest.main()
