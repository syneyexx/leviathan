"""Characterization tests for Gen2 Mission Control / Mission Compiler extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.mission_control import (
    MISSION_TRANSITIONS,
    compile_mission,
    start_mission,
    sync_mission_from_task,
    validate_mission_ir,
)
from gen2.services import MISSION_TRANSITIONS as SERVICES_MISSION_TRANSITIONS
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class MissionControlModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "mission.db"))
        self.events: list[str] = []

        def _record(run_id: str, event_type: str, payload=None, **kwargs):
            self.events.append(event_type)
            return {"run_id": run_id, "event_type": event_type, "payload": payload or {}}

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validate_mission_ir_missing_waves_and_cycles(self) -> None:
        missing = validate_mission_ir({})
        self.assertIn("execution_waves missing", missing)

        cyclic = {
            "execution_waves": [
                {
                    "wave": 0,
                    "steps": [
                        {"id": "a", "agent": "chat", "depends_on": ["b"], "tools": []},
                        {"id": "b", "agent": "chat", "depends_on": ["a"], "tools": []},
                    ],
                }
            ]
        }
        errors = validate_mission_ir(cyclic)
        self.assertTrue(any("dependency cycle" in e for e in errors))

    def test_compile_mission_requires_goal_and_produces_gates_verification(self) -> None:
        with self.assertRaises(ValueError):
            compile_mission(self.store, self.record, "  ")
        mission = compile_mission(self.store, self.record, "Analyse research topic X")
        self.assertEqual(mission["status"], "compiled")
        self.assertTrue(mission.get("gates"))
        self.assertEqual((mission.get("verification") or {}).get("required"), True)
        self.assertEqual((mission.get("verification") or {}).get("status"), "pending")
        self.assertIn("execution_waves", mission["ir"])
        self.assertIn("RUN_CREATED", self.events)
        self.assertIn("PLAN_CREATED", self.events)

    def test_start_mission_blocked_gates_when_unapproved(self) -> None:
        mission = compile_mission(self.store, self.record, "Need approval before start")
        started = start_mission(self.store, self.record, mission["id"])
        self.assertEqual(started["status"], "awaiting_approval")
        self.assertTrue(started.get("blocked_gates"))
        self.assertIn("APPROVAL_REQUESTED", self.events)

    def test_sync_mission_from_task_refuses_completed_without_verification_evidence(self) -> None:
        mission = compile_mission(self.store, self.record, "Evidence required for sync")
        self.store.update_mission(mission["id"], status="running", task_id="task_no_evidence")
        updated = sync_mission_from_task(
            self.store,
            self.record,
            "task_no_evidence",
            status="completed",
            verification={"status": "pending", "required": True},
            step_summary={"total": 2, "completed": 2, "failed": 0, "pending": 0},
        )
        assert updated is not None
        self.assertEqual(updated["status"], "failed")
        ver = updated.get("verification") or {}
        self.assertEqual(ver.get("status"), "failed")
        blockers = (ver.get("acceptance") or {}).get("blockers") or []
        self.assertTrue(any("verification" in b for b in blockers))

    def test_services_facade_still_works(self) -> None:
        self.assertIs(SERVICES_MISSION_TRANSITIONS, MISSION_TRANSITIONS)
        self.assertIn("compiled", MISSION_TRANSITIONS)
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        mission = svc.compile_mission("Facade compile research goal")
        self.assertEqual(mission["status"], "compiled")
        started = svc.start_mission(mission["id"])
        self.assertEqual(started["status"], "awaiting_approval")
        self.assertTrue(started.get("blocked_gates"))
        errors = Gen2Services.validate_mission_ir({"execution_waves": []})
        self.assertIn("execution_waves missing", errors)


if __name__ == "__main__":
    unittest.main()
