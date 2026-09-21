"""Confirmed-outcome packaging failures must not be silently ignored."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class MissionConfirmedOutcomePackagingHonestyTests(unittest.TestCase):
    def test_packaging_failure_is_surfaced(self) -> None:
        from gen2 import mission_control

        source = inspect.getsource(mission_control.sync_mission_from_task)
        self.assertIn("CONFIRMED_OUTCOME_PACKAGING_FAILED", source)
        self.assertIn("confirmed_outcome_error", source)
        self.assertNotIn(
            "except Exception:\n        pass\n    return attach_identity_links(updated) if updated else updated",
            source,
        )


if __name__ == "__main__":
    unittest.main()
