from __future__ import annotations

import unittest
from datetime import UTC, datetime

from schedules import compute_next_run


class ScheduleTimezoneSemanticsTests(unittest.TestCase):
    def test_naive_once_run_at_uses_declared_schedule_timezone(self) -> None:
        # Europe/Amsterdam is UTC+02:00 on 2026-09-14. A naive 09:00 one-shot
        # schedule therefore means 07:00Z, not 09:00Z.
        result = compute_next_run(
            frequency="once",
            timezone="Europe/Amsterdam",
            run_at="2026-09-14T09:00:00",
            after=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        )
        self.assertEqual(result, "2026-09-14T07:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
