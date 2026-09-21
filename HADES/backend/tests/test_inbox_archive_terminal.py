from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inbox import InboxService
from platform_db import PlatformDatabase


class InboxArchiveTerminalTests(unittest.TestCase):
    def test_mark_read_does_not_resurrect_archived_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = PlatformDatabase(str(Path(temp_dir) / "platform.db"))
            db.initialize()
            inbox = InboxService(db)
            item = inbox.create(kind="run_result", title="Done", body="result")
            archived = inbox.archive(item["id"])
            assert archived is not None
            self.assertEqual(archived["status"], "archived")

            after = inbox.mark_read(item["id"])
            assert after is not None
            self.assertEqual(after["status"], "archived")


if __name__ == "__main__":
    unittest.main()
