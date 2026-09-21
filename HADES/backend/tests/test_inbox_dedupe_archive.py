from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inbox import InboxService
from platform_db import PlatformDatabase


class InboxDedupeArchiveTests(unittest.TestCase):
    def test_archived_dedupe_key_can_create_fresh_unread_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = PlatformDatabase(str(Path(temp_dir) / "platform.db"))
            db.initialize()
            inbox = InboxService(db)

            first = inbox.create(
                kind="run_result",
                title="First result",
                body="old",
                dedupe_key="run:42:completed",
            )
            archived = inbox.archive(first["id"])
            assert archived is not None
            self.assertEqual(archived["status"], "archived")

            fresh = inbox.create(
                kind="run_result",
                title="Fresh result",
                body="new",
                dedupe_key="run:42:completed",
            )
            self.assertNotEqual(fresh["id"], first["id"])
            self.assertEqual(fresh["status"], "unread")
            self.assertEqual(fresh["title"], "Fresh result")
            self.assertEqual(fresh["dedupe_key"], "run:42:completed")

            old = db.get_inbox_item(first["id"])
            assert old is not None
            self.assertEqual(old["status"], "archived")
            self.assertIsNone(old["dedupe_key"])


if __name__ == "__main__":
    unittest.main()
