from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app_lifecycle import install_cross_store_integrity_triggers
from database import Database
from platform_db import PlatformDatabase, utc_now


class ConversationForgetAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "hades.db"
        self.database = Database(str(self.db_path))
        self.platform_db = PlatformDatabase(str(self.db_path))
        self.database.initialize()
        self.platform_db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_conversation_knowledge(self, conversation_id: str = "conv_atomic") -> tuple[str, str]:
        now = utc_now()
        source_id = "src_atomic"
        chunk_id = "chunk_atomic"
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO conversations(id,title,model_id,system_prompt_override,working_state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (conversation_id, "Atomic", None, None, None, now, now),
            )
        with self.platform_db.connection() as db:
            db.execute(
                "INSERT INTO knowledge_sources(id,title,source_type,uri,local_path,content_hash,metadata,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (source_id, "Conversation", "conversation", f"conversation:{conversation_id}", None, "hash", "{}", "ready", now, now),
            )
            db.execute(
                "INSERT INTO knowledge_chunks(id,source_id,sequence,heading,content,content_hash,token_estimate,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (chunk_id, source_id, 0, "", "private learned text", "chunkhash", 3, now),
            )
            db.execute(
                "INSERT INTO knowledge_fts(chunk_id,source_id,title,heading,content) VALUES(?,?,?,?,?)",
                (chunk_id, source_id, "Conversation", "", "private learned text"),
            )
        return source_id, chunk_id

    def test_delete_forgets_searchable_conversation_knowledge_in_same_transaction(self) -> None:
        source_id, chunk_id = self._seed_conversation_knowledge()
        self.assertTrue(install_cross_store_integrity_triggers(self.database, self.platform_db))

        self.assertTrue(self.database.delete_conversation("conv_atomic"))

        with self.platform_db.connection() as db:
            source = db.execute("SELECT status FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
            chunks = db.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE id=?", (chunk_id,)).fetchone()[0]
            fts = db.execute("SELECT COUNT(*) FROM knowledge_fts WHERE chunk_id=?", (chunk_id,)).fetchone()[0]
        self.assertEqual(source["status"], "forgotten")
        self.assertEqual(chunks, 0)
        self.assertEqual(fts, 0)

    def test_cleanup_failure_rolls_back_primary_conversation_delete(self) -> None:
        self._seed_conversation_knowledge()
        self.assertTrue(install_cross_store_integrity_triggers(self.database, self.platform_db))
        with self.platform_db.connection() as db:
            db.execute("DROP TABLE knowledge_fts")

        with self.assertRaises(sqlite3.OperationalError):
            self.database.delete_conversation("conv_atomic")

        with self.database.connection() as db:
            remaining = db.execute("SELECT COUNT(*) FROM conversations WHERE id='conv_atomic'").fetchone()[0]
        self.assertEqual(remaining, 1)

    def test_trigger_not_installed_across_different_sqlite_files(self) -> None:
        other = PlatformDatabase(str(Path(self.tmp.name) / "other.db"))
        other.initialize()
        self.assertFalse(install_cross_store_integrity_triggers(self.database, other))


if __name__ == "__main__":
    unittest.main()
