from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from approvals import ApprovalService
from database import Database
from inbox import InboxService
from platform_db import PlatformDatabase


class ApprovalTimeoutRemainsPendingTests(unittest.TestCase):
    def test_timeout_stays_pending_never_auto_allows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "hades.db"
            database = Database(str(db_path))
            database.initialize()
            platform = PlatformDatabase(str(db_path))
            platform.initialize()
            inbox = InboxService(platform)
            approvals = ApprovalService(platform, inbox)
            req = approvals.create_tool_approval(
                plugin_id="demo",
                tool_name="write_file",
                arguments={"path": "a.txt"},
                expected_effect="write",
                expires_in_seconds=60,
            )
            past = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="seconds")
            with platform.connection() as db:
                db.execute(
                    "UPDATE approval_requests SET expires_at=? WHERE id=?",
                    (past, req["id"]),
                )
            self.assertEqual(approvals.expire_due(), 0)
            pending = approvals.list_pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["status"], "pending")
            self.assertTrue(pending[0]["timed_out"])
            self.assertFalse(pending[0]["auto_allowed"])
            decided = approvals.decide(req["id"], approve=False)
            self.assertEqual(decided["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
