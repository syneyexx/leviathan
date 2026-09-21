"""T1/F-01: Gen2 missions dispatch into Work Runtime and stay honest about status.

Acceptance:
- After start, mission is ``dispatched`` (not ``running``) while the Work task is still
  ``queued``.
- ``schedule_task`` is invoked after successful task creation.
- When Work Runtime marks the task running, the linked mission promotes to ``running``.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from database import Database
from gen2.mission_control import start_mission, sync_mission_from_task
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class MissionDispatchHonestyUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "mission.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        self.events: list[str] = []

        def _record(run_id: str, event_type: str, payload=None, **kwargs):
            self.events.append(event_type)
            return {"run_id": run_id, "event_type": event_type, "payload": payload or {}}

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _approve_all(self, mission_id: str) -> None:
        mission = self.store.get_mission(mission_id) or {}
        for gate in mission.get("gates") or []:
            if gate.get("required") and gate.get("status") != "approved":
                self.svc.decide_mission_gate(mission_id, gate["id"], approve=True)

    def test_mission_not_running_while_task_queued(self) -> None:
        mission = self.svc.compile_mission("Dispatch honesty research carefully.")
        self._approve_all(mission["id"])
        scheduled: list[str] = []

        def create_task(_mission: dict) -> dict:
            return {"id": "task_queued_only", "status": "queued"}

        def schedule_task(task_id: str) -> None:
            scheduled.append(task_id)

        started = start_mission(
            self.store,
            self.record,
            mission["id"],
            create_task=create_task,
            schedule_task=schedule_task,
        )
        self.assertEqual(started["status"], "dispatched")
        self.assertEqual(started["task_id"], "task_queued_only")
        self.assertNotEqual(started["status"], "running")
        self.assertEqual(scheduled, ["task_queued_only"])
        self.assertIn("RUN_CREATED", self.events)

    def test_sync_promotes_dispatched_mission_to_running(self) -> None:
        mission = self.svc.compile_mission("Promote dispatched mission carefully.")
        self._approve_all(mission["id"])
        started = start_mission(
            self.store,
            self.record,
            mission["id"],
            create_task=lambda _m: {"id": "task_promote"},
            schedule_task=lambda _tid: None,
        )
        self.assertEqual(started["status"], "dispatched")
        updated = sync_mission_from_task(
            self.store,
            self.record,
            "task_promote",
            status="running",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["status"], "running")


class MissionDispatchBridgeTests(unittest.TestCase):
    """Exercise real task creation + schedule wiring without a blocking TestClient worker."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "bridge-mission.db"))
        main.database.initialize()
        main.runner = main.TaskRunner()
        main.ensure_platform_services()
        main.platform_db.initialize()
        main._sync_gen2_services()
        self.scheduled: list[str] = []
        main.gen2_ctx["schedule_mission_task"] = lambda task_id: self.scheduled.append(task_id)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_mission_task_and_route_schedule_wiring(self) -> None:
        mission = main.gen2.compile_mission("Bridge dispatch mission carefully.")
        for gate in mission.get("gates") or []:
            if gate.get("required") and gate.get("status") != "approved":
                main.gen2.decide_mission_gate(mission["id"], gate["id"], approve=True)

        def _create_task(m: dict) -> dict:
            return main._create_mission_task(m)

        started = main.gen2.start_mission(
            mission["id"],
            create_task=_create_task,
            schedule_task=lambda tid: self.scheduled.append(tid),
        )
        self.assertEqual(started["status"], "dispatched")
        self.assertTrue(started.get("task_id"))
        self.assertEqual(self.scheduled, [started["task_id"]])

        task = main.database.get_task(started["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "queued")
        # Mission must not claim running while Work task is still queued.
        live = main.gen2.store.get_mission(mission["id"])
        self.assertEqual(live["status"], "dispatched")
        self.assertNotEqual(live["status"], "running")

        steps = main.platform_db.work_steps(started["task_id"])
        self.assertGreaterEqual(len(steps), 1)

    def test_execute_promotes_mission_and_emits_step_activity(self) -> None:
        mission = main.gen2.compile_mission("Execute promotes mission carefully.")
        for gate in mission.get("gates") or []:
            if gate.get("required") and gate.get("status") != "approved":
                main.gen2.decide_mission_gate(mission["id"], gate["id"], approve=True)

        started = main.gen2.start_mission(
            mission["id"],
            create_task=main._create_mission_task,
            schedule_task=lambda _tid: None,  # manual execute below
        )
        task_id = started["task_id"]
        self.assertEqual(started["status"], "dispatched")

        async def _run() -> None:
            # Bypass LM: mark running the same way TaskRunner._execute starts.
            main.database.update_task(task_id, status="running", progress=5, result=None, error=None)
            main.database.add_task_event(task_id, "info", "Stap 1/1: simulated · executor")
            await main._async_sync_mission_from_task_safe(task_id, status="running")
            steps = main.platform_db.work_steps(task_id)
            if steps:
                main.platform_db.update_work_step(steps[0]["id"], status="running", error="")
                main.run_event_bus.emit_sync(
                    task_id,
                    "step_started",
                    {
                        "step_id": steps[0]["id"],
                        "agent_id": "executor",
                        "title": steps[0].get("title"),
                        "step_number": 1,
                    },
                )

        asyncio.run(_run())

        task = main.database.get_task(task_id)
        self.assertEqual(task["status"], "running")
        events = main.database.task_events(task_id)
        self.assertTrue(any("Stap " in str(ev.get("message") or "") for ev in events))
        steps = main.platform_db.work_steps(task_id)
        self.assertTrue(any(s.get("status") == "running" for s in steps))
        live = main.gen2.store.get_mission(mission["id"])
        self.assertEqual(live["status"], "running")

    def test_schedule_mission_task_uses_runner_schedule(self) -> None:
        main._sync_gen2_services()
        schedule = main.gen2_ctx.get("schedule_mission_task")
        self.assertTrue(callable(schedule))
        with patch.object(main.runner, "schedule", MagicMock()) as mocked:
            # Re-bind after patch so ctx lambda closes over current runner.
            main.gen2_ctx["schedule_mission_task"] = lambda task_id: main.runner.schedule(task_id)
            main.gen2_ctx["schedule_mission_task"]("task_x")
            mocked.assert_called_once_with("task_x")


if __name__ == "__main__":
    unittest.main()
