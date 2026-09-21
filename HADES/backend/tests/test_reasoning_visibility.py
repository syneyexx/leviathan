"""Focused tests for critic checklist, difficulty router meta, and durable checkpoint resume."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from database import Database
from platform_db import PlatformDatabase
from reasoning.profiles import resolve_reasoning_profile
from reasoning.understanding import build_route_decision
from reasoning.verification import (
    build_acceptance_checklist,
    parse_verification_result,
    verification_allows_success,
)


class AcceptanceChecklistTests(unittest.TestCase):
    def test_unmet_checklist_blocks_even_when_passed_flag_true(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Bijna","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"criterion":"Moet X","met":false,"note":"ontbreekt"},'
            '{"criterion":"Moet Y","met":true,"note":"ok"}]}'
        )
        self.assertIsNotNone(parsed)
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=[{"title": "Stap", "agent_id": "executor", "output": "ok"}],
            acceptance_criteria=["Moet X", "Moet Y"],
        )
        self.assertFalse(ok)
        self.assertIn("Acceptatiecriteria", reason)
        checklist = build_acceptance_checklist(["Moet X", "Moet Y"], result=parsed)
        self.assertEqual([row.met for row in checklist], [False, True])

    def test_passed_with_all_criteria_met(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Klaar","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"criterion":"Klaar resultaat","met":true,"note":"ok"}]}'
        )
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=[{"title": "Stap", "agent_id": "executor", "output": "ok"}],
            acceptance_criteria=["Klaar resultaat"],
        )
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "")


class DifficultyRouterVisibilityTests(unittest.TestCase):
    def test_simple_ask_takes_cheap_path(self) -> None:
        profile, spec, meta = resolve_reasoning_profile("Hoi, hoe gaat het?", "adaptive")
        route = build_route_decision(
            spec,
            requested_profile=profile,
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertEqual(profile, "fast")
        self.assertEqual(route.target, "direct_chat")
        self.assertEqual(meta.get("complexity_kind") or meta["complexity"].get("kind"), "uncalibrated_hint")
        self.assertFalse(route.require_verification)

    def test_hard_ask_raises_profile_and_specialist_target(self) -> None:
        text = (
            "Plan een end-to-end migratie van de architectuur met multi-agent orchestratie, "
            "refactor de codebase, schrijf tests, en gebruik plugins om de deploy te verifiëren."
        )
        profile, spec, meta = resolve_reasoning_profile(text, "adaptive")
        route = build_route_decision(
            spec,
            requested_profile=profile,
            network_policy="block",
            plugin_tools_enabled=True,
        )
        self.assertIn(profile, {"high", "maximum"})
        self.assertIn(route.target, {"work_runtime", "tool_loop", "analysis", "specialist_agent"})
        self.assertTrue(route.rationale)
        self.assertEqual(meta.get("complexity_kind") or meta["complexity"].get("kind"), "uncalibrated_hint")


class DurableCheckpointResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        main.database = Database(str(root / "core.db"))
        main.database.initialize()
        main.runner = main.TaskRunner()
        main.platform_db = PlatformDatabase(str(root / "plat.db"))
        main.ensure_platform_services()
        main.platform_db.initialize()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_resume_checkpoint_keeps_completed_and_requeues_failed(self) -> None:
        task = main.database.create_task("Checkpoint resume", "Doe iets", "executor", "normal", None)
        main.platform_db.replace_work_plan(
            task["id"],
            [
                {
                    "step_id": "step-1",
                    "agent_id": "executor",
                    "kind": "work",
                    "title": "Done step",
                    "instruction": "already done",
                    "depends_on": [],
                },
                {
                    "step_id": "step-2",
                    "agent_id": "executor",
                    "kind": "work",
                    "title": "Failed step",
                    "instruction": "needs retry",
                    "depends_on": ["step-1"],
                },
            ],
        )
        steps = main.platform_db.work_steps(task["id"])
        main.platform_db.update_work_step(steps[0]["id"], status="completed", output="ok")
        main.platform_db.update_work_step(steps[1]["id"], status="failed", error="boom")
        main.platform_db.add_work_checkpoint(
            task["id"],
            {
                "phase": "verification_failed",
                "acceptance_criteria": ["Done"],
                "acceptance_checklist": [{"criterion": "Done", "met": False, "note": "boom"}],
                "issues": ["boom"],
            },
        )
        main.database.update_task(task["id"], status="failed", progress=40, error="boom")

        response = self.client.post(f"/api/tasks/{task['id']}/resume-checkpoint")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["resumed"])
        refreshed = main.platform_db.work_steps(task["id"])
        by_title = {step["title"]: step for step in refreshed}
        self.assertEqual(by_title["Done step"]["status"], "completed")
        self.assertEqual(by_title["Failed step"]["status"], "queued")
        # Resume must requeue; response status is the contract (get_task can race workers).
        self.assertIn(body.get("task", {}).get("status") or body.get("status") or "", {"queued", "running"})
        live = (main.database.get_task(task["id"]) or {}).get("status")
        self.assertIn(live, {"queued", "running", "completed", "failed"})

        # Clean retry still clears work state. Resume may have scheduled a worker —
        # force a terminal failed state and avoid racing a live "running" task.
        cancel = self.client.post(f"/api/tasks/{task['id']}/cancel")
        self.assertIn(cancel.status_code, {200, 409}, cancel.text)
        main.database.update_task(task["id"], status="failed", progress=0, error="x")
        retry = self.client.post(f"/api/tasks/{task['id']}/retry")
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(main.platform_db.work_steps(task["id"]), [])


if __name__ == "__main__":
    unittest.main()
