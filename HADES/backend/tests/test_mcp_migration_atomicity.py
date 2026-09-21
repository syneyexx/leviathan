from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from mcp_host.store import ensure_mcp_schema


class McpMigrationAtomicityTests(unittest.TestCase):
    def test_v16_rebuild_failure_preserves_original_execution_history(self) -> None:
        """Known defect: v16 table rebuild is not wrapped in an explicit transaction.

        Fault-inject at ALTER TABLE after the script has already copied and dropped
        the original table. A migration failure must leave the pre-migration table
        and its rows intact. Remove expectedFailure when the rebuild is atomic.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp-migration.db"
            db = sqlite3.connect(path)
            try:
                db.executescript(
                    """
                    CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES(15, '2026-01-01T00:00:00+00:00');

                    CREATE TABLE mcp_executions (
                        id TEXT PRIMARY KEY,
                        server_id TEXT NOT NULL,
                        tool_id TEXT NOT NULL,
                        tool_call_id TEXT,
                        status TEXT NOT NULL,
                        error_kind TEXT,
                        started_at TEXT,
                        ended_at TEXT,
                        duration_ms REAL,
                        input_json TEXT,
                        result_json TEXT,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        idempotency_key TEXT UNIQUE
                    );
                    INSERT INTO mcp_executions(
                        id, server_id, tool_id, status, cancel_requested, idempotency_key
                    ) VALUES('exec_1', 'srv_1', 'tool_1', 'completed', 0, 'same-key');
                    """
                )

                def deny_rename(action, arg1, arg2, database_name, trigger_name):
                    if action == sqlite3.SQLITE_ALTER_TABLE:
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                db.set_authorizer(deny_rename)
                with self.assertRaises(sqlite3.DatabaseError):
                    ensure_mcp_schema(db)
                db.set_authorizer(None)

                tables = {
                    str(row[0])
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                self.assertIn("mcp_executions", tables)
                row = db.execute(
                    "SELECT id, server_id, tool_id, status, idempotency_key FROM mcp_executions WHERE id='exec_1'"
                ).fetchone()
                self.assertEqual(row, ("exec_1", "srv_1", "tool_1", "completed", "same-key"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
