#!/usr/bin/env python3
"""Schedule ticker must mark claimed occurrences failed on dispatch errors (not silent linger)."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Database  # noqa: E402
from platform_db import PlatformDatabase  # noqa: E402
from schedules import ScheduleService  # noqa: E402
from inbox import InboxService  # noqa: E402


class ScheduleDispatchHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.database = Database(str(root / "hades.db"))
        self.database.initialize()
        self.platform = PlatformDatabase(str(root / "platform.db"))
        self.platform.initialize()
        self.inbox = InboxService(self.platform)
        self.clock = {"now": datetime(2026, 3, 28, 10, 0, tzinfo=UTC)}
        self.svc = ScheduleService(self.platform, self.inbox, clock=lambda: self.clock["now"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dispatch_exception_marks_occurrence_failed(self) -> None:
        import main as main_mod

        task = self.database.create_task("Daily", "doe werk", "executor", "normal", None)
        self.database.update_task(task["id"], status="completed", progress=100)
        schedule = self.svc.attach_schedule(
            task["id"],
            frequency="daily",
            timezone="UTC",
            time_of_day="09:00",
            enabled=True,
        )
        self.platform.update_task_schedule(
            schedule["id"],
            next_run_at=self.clock["now"].isoformat(),
            updated_at=self.clock["now"].isoformat(),
        )

        runner = main_mod.TaskRunner()

        async def _one_tick() -> None:
            with patch.object(main_mod, "schedule_service", self.svc), patch.object(
                main_mod, "database", self.database
            ), patch.object(main_mod, "inbox_service", self.inbox), patch.object(
                main_mod, "ensure_platform_services", lambda: self.platform
            ), patch.object(self.database, "create_task", side_effect=RuntimeError("boom")):
                tick = asyncio.create_task(runner.schedule_ticker())
                await asyncio.sleep(0.35)
                tick.cancel()
                try:
                    await tick
                except asyncio.CancelledError:
                    pass

        asyncio.run(_one_tick())

        with self.platform.connection() as db:
            row = db.execute(
                "SELECT status, result_summary FROM task_occurrences WHERE schedule_id = ? ORDER BY rowid DESC LIMIT 1",
                (schedule["id"],),
            ).fetchone()
        self.assertIsNotNone(row, "expected an occurrence row after failed dispatch")
        self.assertEqual(row["status"], "failed")
        self.assertIn("schedule_dispatch_failed", str(row["result_summary"] or ""))


if __name__ == "__main__":
    unittest.main()
