"""Mission sync safe wrapper must never invent ok=True."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


class MissionSyncSafeHonestyTests(unittest.TestCase):
    def test_none_mission_is_not_ok(self) -> None:
        import main as hades_main

        hades_main.gen2.sync_mission_from_task = MagicMock(return_value=None)
        result = hades_main._sync_mission_from_task_safe("task-1", status="completed")
        self.assertIs(result.get("ok"), False)
        self.assertEqual(result.get("error"), "no_linked_mission")

    def test_status_mismatch_is_not_ok(self) -> None:
        import main as hades_main

        hades_main.gen2.sync_mission_from_task = MagicMock(
            return_value={"id": "m1", "status": "failed", "task_id": "task-1"}
        )
        result = hades_main._sync_mission_from_task_safe("task-1", status="completed")
        self.assertIs(result.get("ok"), False)
        self.assertEqual(result.get("error"), "mission_sync_refused_or_demoted")

    def test_matching_status_is_ok(self) -> None:
        import main as hades_main

        hades_main.gen2.sync_mission_from_task = MagicMock(
            return_value={"id": "m1", "status": "failed", "task_id": "task-1"}
        )
        result = hades_main._sync_mission_from_task_safe("task-1", status="failed")
        self.assertIs(result.get("ok"), True)
        self.assertEqual(result.get("status"), "failed")

    def test_callers_do_not_default_missing_ok_to_true(self) -> None:
        source = (BACKEND / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('sync.get("ok", True)', source)
        self.assertNotIn('or {"ok": True, "task_id": task_id}', source)
        self.assertIn("no_linked_mission", source)


if __name__ == "__main__":
    unittest.main()
