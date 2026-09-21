"""T7/F-05+F-16: Work cancel stops LM runs; specialists stay off the event loop."""

from __future__ import annotations

import asyncio
import inspect
import unittest
from pathlib import Path
from unittest import mock


class TaskRunnerCancelLmTests(unittest.TestCase):
    def test_cancel_running_task_remembers_and_schedules_lm_cancel(self) -> None:
        from main import TaskRunner

        runner = TaskRunner()
        task_id = "task-cancel-lm-1"
        fake_task = {
            "id": task_id,
            "status": "running",
            "control_state": "active",
            "progress": 40,
        }
        created: list[str] = []

        class FakeLoop:
            def create_task(self, coro, name=None):
                created.append(name or "task")
                # Close the coroutine to avoid "never awaited" warnings.
                if hasattr(coro, "close"):
                    coro.close()
                return mock.Mock()

        with mock.patch("main.database") as db, mock.patch(
            "main.work_control_transition_allowed", return_value=True
        ), mock.patch("main.remember_cancelled_run") as remember, mock.patch(
            "main.cancel_lm_run", new=mock.AsyncMock(return_value={"ok": True})
        ), mock.patch(
            "main._sync_mission_from_task_safe"
        ), mock.patch(
            "main.asyncio.get_running_loop", return_value=FakeLoop()
        ):
            db.get_task.return_value = fake_task
            db.update_task.return_value = {**fake_task, "status": "cancelled"}
            ok = runner.cancel(task_id)

        self.assertTrue(ok)
        remember.assert_called_with(task_id)
        self.assertTrue(any("cancel-lm" in str(name) for name in created))
        self.assertEqual(len(created), 1)

    def test_queue_is_bounded(self) -> None:
        from main import TaskRunner

        runner = TaskRunner()
        self.assertGreater(runner.queue.maxsize, 0)


class AgentRuntimeOffloadTests(unittest.TestCase):
    def test_try_run_agent_step_offloads_sync_handlers(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("agent_runtimes.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.to_thread(handler, instruction, deps)", source)

    def test_try_run_agent_step_is_async(self) -> None:
        from agent_runtimes import try_run_agent_step

        self.assertTrue(inspect.iscoroutinefunction(try_run_agent_step))


class MissionStartOffloadTests(unittest.TestCase):
    def test_gen2_start_route_uses_to_thread(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("gen2/routes.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.to_thread", source)
        self.assertIn("start_mission", source)


class WorkRouteCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_route_awaits_cancel_lm_run(self) -> None:
        from work_routes import mount_work_routes

        calls: list[str] = []

        class FakeRunner:
            def cancel(self, task_id: str) -> bool:
                calls.append(f"runner:{task_id}")
                return True

        class FakeDb:
            def get_task(self, task_id: str):
                return {"id": task_id, "status": "running", "control_state": "active"}

        async def fake_cancel_lm(run_id: str):
            calls.append(f"lm:{run_id}")
            return {"ok": True, "cancelled": True, "run_id": run_id, "clients": 0}

        router = mount_work_routes(
            {
                "database": FakeDb(),
                "runner": FakeRunner(),
                "platform_db": mock.Mock(),
                "ensure_platform_services": lambda: None,
            }
        )
        # Find cancel endpoint handler
        cancel_fn = None
        for route in router.routes:
            if getattr(route, "path", "") == "/tasks/{task_id}/cancel" and "POST" in getattr(route, "methods", set()):
                cancel_fn = route.endpoint
                break
        self.assertIsNotNone(cancel_fn)
        with mock.patch("work_routes.cancel_lm_run", side_effect=fake_cancel_lm):
            result = await cancel_fn("tid-9")
        self.assertIn("runner:tid-9", calls)
        self.assertIn("lm:tid-9", calls)
        self.assertEqual(result["status"], "running")  # FakeDb returns same snapshot


if __name__ == "__main__":
    unittest.main()
