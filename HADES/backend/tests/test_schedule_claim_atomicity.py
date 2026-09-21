from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from platform_db import PlatformDatabase
from schedules import ScheduleService


class ScheduleClaimAtomicityTests(unittest.TestCase):
    def test_claim_and_schedule_advance_are_one_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = PlatformDatabase(str(Path(temp_dir) / "platform.db"))
            db.initialize()
            now = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
            service = ScheduleService(db, clock=lambda: now)
            schedule = service.attach_schedule(
                "task_atomic",
                frequency="daily",
                timezone="UTC",
                time_of_day="09:00",
                enabled=True,
            )
            planned = now.isoformat(timespec="seconds")
            db.update_task_schedule(schedule["id"], next_run_at=planned, updated_at=planned)
            due = db.get_task_schedule(schedule["id"])
            assert due is not None
            occurrence_id = f"{schedule['id']}:{planned}"

            # SQLite-level fault injection: abort the schedule advance after the
            # occurrence claim statement. A correct implementation rolls both
            # statements back together. schedule ids are generated as sched_<hex>.
            schedule_id = str(schedule["id"])
            self.assertTrue(schedule_id.replace("_", "").isalnum())
            with db.connection() as conn:
                conn.executescript(
                    f"""CREATE TRIGGER fail_schedule_advance
                        BEFORE UPDATE OF next_run_at ON task_schedules
                        WHEN NEW.id = '{schedule_id}'
                        BEGIN
                          SELECT RAISE(ABORT, 'advance failed');
                        END;"""
                )

            with self.assertRaises(sqlite3.IntegrityError):
                service.claim_occurrence(due)

            with db.connection() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM task_occurrences WHERE occurrence_id=?",
                    (occurrence_id,),
                ).fetchone()[0]
            self.assertEqual(count, 0, "claim must roll back when schedule advance fails")

            with db.connection() as conn:
                conn.execute("DROP TRIGGER fail_schedule_advance")

            retry_schedule = db.get_task_schedule(schedule["id"])
            assert retry_schedule is not None
            claimed = service.claim_occurrence(retry_schedule)
            self.assertIsNotNone(claimed)
            recovered = db.get_task_schedule(schedule["id"])
            assert recovered is not None
            self.assertNotEqual(recovered["next_run_at"], planned)


if __name__ == "__main__":
    unittest.main()


class ScheduleRestartSurvivalTests(unittest.TestCase):
    def test_daily_schedule_claimable_after_process_restart(self) -> None:
        from database import Database
        from inbox import InboxService

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "hades.db"
            database = Database(str(db_path))
            database.initialize()
            platform = PlatformDatabase(str(db_path))
            platform.initialize()
            inbox = InboxService(platform)
            clock = {"now": datetime(2026, 3, 28, 10, 0, tzinfo=UTC)}
            svc = ScheduleService(platform, inbox, clock=lambda: clock["now"])
            task = database.create_task("Daily", "doe werk", "executor", "normal", None)
            schedule = svc.attach_schedule(
                task["id"],
                frequency="daily",
                timezone="UTC",
                time_of_day="09:00",
                enabled=True,
            )
            # New process: fresh service objects, same SQLite file.
            platform2 = PlatformDatabase(str(db_path))
            platform2.initialize()
            inbox2 = InboxService(platform2)
            clock["now"] = datetime(2026, 3, 29, 9, 5, tzinfo=UTC)
            svc2 = ScheduleService(platform2, inbox2, clock=lambda: clock["now"])
            due = svc2.due_schedules()
            self.assertTrue(any(item["id"] == schedule["id"] for item in due))
            claimed = svc2.claim_occurrence(next(item for item in due if item["id"] == schedule["id"]))
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["status"], "claimed")
