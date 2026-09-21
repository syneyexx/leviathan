"""Mission Control monster items B1.1 / B1.5 / B1.6 / B1.8 / B1.9 — real store + API."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from gen2.mission_control import (
    compile_mission,
    decide_mission_gate,
    diff_mission_revision_versions,
    list_mission_revisions,
    mission_identity_links,
    portfolio_view,
    replan_mission,
    sync_mission_from_task,
    validate_mission_ir,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store
from reasoning.long_task_resume import confirmed_outcome_from_task_and_mission


class MissionIRCharacterizationTests(unittest.TestCase):
    """B1.1 — compile_mission produces typed Mission IR fields."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "ir.db"))
        self.events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            self.events.append(row)
            return row

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_compile_mission_ir_fields(self) -> None:
        mission = compile_mission(
            self.store,
            self.record,
            "Doe een volledige intelligence-analyse van NVIDIA earnings.",
            title="NVIDIA IR",
        )
        self.assertEqual(mission["status"], "compiled")
        ir = mission["ir"]
        self.assertEqual(ir["version"], 1)
        self.assertTrue(ir["goal"])
        self.assertEqual(ir["domain"], "finance")
        self.assertTrue(ir["objectives"])
        self.assertTrue(ir["subtasks"])
        self.assertIsInstance(ir["dependencies"], list)
        self.assertTrue(ir["agents"])
        self.assertIn("planner", ir["models"])
        self.assertTrue(ir["plugins_tools"])
        self.assertIn("input", ir["io_contracts"])
        self.assertIn("output", ir["io_contracts"])
        self.assertTrue(ir["context_budgets"])
        self.assertIn("max_tokens", ir["token_time_tool_budgets"])
        self.assertIn("max_replans", ir["retry_policies"])
        self.assertTrue(ir["checkpoints"])
        self.assertTrue(ir["human_approval_gates"])
        self.assertTrue(ir["acceptance_criteria"])
        self.assertTrue(ir["acceptance_checks"])
        self.assertTrue(ir["verification_requirements"])
        self.assertTrue(ir["artifacts"])
        self.assertTrue(ir["execution_waves"])
        self.assertFalse(validate_mission_ir(ir))
        # Waves have deps / agents / tools.
        step = ir["execution_waves"][0]["steps"][0]
        self.assertTrue(step["id"])
        self.assertTrue(step["agent"])
        self.assertIsInstance(step.get("tools"), list)
        self.assertIn("links", mission)
        self.assertEqual(mission["links"]["mission_id"], mission["id"])


class PortfolioAndRevisionsTests(unittest.TestCase):
    """B1.5 portfolio + B1.6 persisted revisions/diff."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "port.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_portfolio_filter_by_status(self) -> None:
        a = self.svc.compile_mission("Research ACME market analogues carefully.")
        b = self.svc.compile_mission("Refactor codebase tests carefully.")
        gate = a["gates"][0]["id"]
        self.svc.decide_mission_gate(a["id"], gate, approve=True, note="ok")
        port = portfolio_view(self.store, status="ready")
        ids = {m["id"] for m in port["missions"]}
        self.assertIn(a["id"], ids)
        self.assertNotIn(b["id"], ids)
        row = next(m for m in port["missions"] if m["id"] == a["id"])
        self.assertEqual(row["status"], "ready")
        self.assertIn("domain", row)
        self.assertIn("budgets", row)
        self.assertIn("gates_summary", row)
        self.assertIn("pending_required", row["gates_summary"])
        all_port = self.svc.portfolio_missions()
        self.assertGreaterEqual(all_port["count"], 2)
        self.assertIn("by_status", all_port)

    def test_mission_revisions_persist_and_diff(self) -> None:
        mission = self.svc.compile_mission("Research bounded replan carefully.")
        revs = list_mission_revisions(self.store, mission["id"])
        self.assertGreaterEqual(len(revs), 1)
        self.assertEqual(revs[0]["cause"], "compile")
        gate = mission["gates"][0]["id"]
        decide_mission_gate(self.store, self.svc.record, mission["id"], gate, approve=True, note="go")
        replan_mission(self.store, self.svc.record, mission["id"], "verification", note="retry")
        revs2 = self.svc.list_mission_revisions(mission["id"])
        self.assertGreaterEqual(len(revs2), 3)
        versions = sorted(r["version"] for r in revs2)
        diff = diff_mission_revision_versions(self.store, mission["id"], versions[0], versions[-1])
        self.assertGreaterEqual(diff["change_count"], 1)
        self.assertEqual(diff["from_version"], versions[0])
        self.assertEqual(diff["to_version"], versions[-1])


class IdentityAndOutcomeTests(unittest.TestCase):
    """B1.8 identity links + B1.9 confirmed outcome consistency."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "id.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_identity_links_mission_task_run_step_artifact(self) -> None:
        mission = self.svc.compile_mission("Analyse research topic depth carefully.")
        # Simulate start attachment.
        updated = self.store.update_mission(
            mission["id"],
            task_id="task_abc",
            execution_id="mexec_1",
            status="running",
        )
        links = mission_identity_links(updated)
        self.assertEqual(links["mission_id"], mission["id"])
        self.assertEqual(links["task_id"], "task_abc")
        self.assertEqual(links["execution_id"], "mexec_1")
        self.assertEqual(links["run_id"], "mexec_1")
        self.assertTrue(links["step_ids"])
        self.assertTrue(links["steps"])
        self.assertTrue(any(a.get("role") == "planned" for a in links["artifacts"]))
        self.assertTrue(links["gates"])
        # Flight event payload carries identity_links from compile.
        events = self.store.list_run_events(mission["id"])
        plan_events = [e for e in events if e["event_type"] in {"PLAN", "RUN_CREATED"}]
        self.assertTrue(plan_events)
        self.assertIn("identity_links", plan_events[0]["payload"])

    def test_confirmed_outcome_sync_aligns_mission_and_helper(self) -> None:
        mission = self.svc.compile_mission("Betrouwbare sync outcome test")
        self.store.update_mission(mission["id"], task_id="task_out", status="running", execution_id="exec_out")
        synced = sync_mission_from_task(
            self.store,
            self.svc.record,
            "task_out",
            status="completed",
            verification={"status": "passed", "evidence_refs": ["step:s1"]},
            step_summary={"total": 2, "completed": 2, "failed": 0, "pending": 0},
        )
        self.assertIsNotNone(synced)
        assert synced is not None
        outcome = synced.get("confirmed_outcome")
        self.assertIsNotNone(outcome)
        helper = confirmed_outcome_from_task_and_mission(
            task={
                "id": "task_out",
                "status": "completed",
                "verification": {"status": "passed", "evidence_refs": ["step:s1"]},
                "step_summary": {"total": 2, "completed": 2, "failed": 0, "pending": 0},
            },
            mission=synced,
        )
        self.assertEqual(outcome["status"], helper.status)
        self.assertEqual(outcome["confirmed"], helper.confirmed)
        self.assertEqual(outcome["mission_id"], helper.mission_id)
        self.assertEqual(outcome["task_id"], helper.task_id)

        # Task claims completed but verification fails → mission failed; same confirmed outcome.
        mission2 = self.svc.compile_mission("Sync fail evidence")
        self.store.update_mission(mission2["id"], task_id="task_fail", status="running")
        failed = sync_mission_from_task(
            self.store,
            self.svc.record,
            "task_fail",
            status="completed",
            verification={"status": "failed", "evidence_refs": []},
            step_summary={"total": 1, "completed": 0, "failed": 1},
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["confirmed_outcome"]["status"], "failed")
        self.assertTrue(failed["confirmed_outcome"]["confirmed"])


class MissionControlApiProductTests(unittest.TestCase):
    """API product coverage for portfolio / revisions / links."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api-monster.db"))
        main.runner = main.TaskRunner()
        main.ensure_platform_services()
        main._sync_gen2_services()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_portfolio_revisions_links_api(self) -> None:
        compiled = self.client.post(
            "/api/gen2/missions/compile",
            json={"goal": "Portfolio API mission research carefully"},
        )
        self.assertEqual(compiled.status_code, 201)
        mid = compiled.json()["id"]
        self.assertIn("links", compiled.json())

        port = self.client.get("/api/gen2/missions/portfolio")
        self.assertEqual(port.status_code, 200)
        body = port.json()
        self.assertIn("missions", body)
        self.assertGreaterEqual(body["count"], 1)

        filtered = self.client.get("/api/gen2/missions/portfolio?status=compiled")
        self.assertEqual(filtered.status_code, 200)
        self.assertTrue(all(m["status"] == "compiled" for m in filtered.json()["missions"]))

        links = self.client.get(f"/api/gen2/missions/{mid}/links")
        self.assertEqual(links.status_code, 200)
        self.assertEqual(links.json()["mission_id"], mid)
        self.assertTrue(links.json()["step_ids"])

        revs = self.client.get(f"/api/gen2/missions/{mid}/revisions")
        self.assertEqual(revs.status_code, 200)
        self.assertGreaterEqual(len(revs.json()), 1)

        gate_id = compiled.json()["gates"][0]["id"]
        self.client.post(
            f"/api/gen2/missions/{mid}/gates/{gate_id}",
            json={"approve": True, "note": "api"},
        )
        revs2 = self.client.get(f"/api/gen2/missions/{mid}/revisions").json()
        versions = sorted(r["version"] for r in revs2)
        diff = self.client.get(
            f"/api/gen2/missions/{mid}/revisions/diff",
            params={"from_version": versions[0], "to_version": versions[-1]},
        )
        self.assertEqual(diff.status_code, 200)
        self.assertIn("change_count", diff.json())
        self.assertIn("changes", diff.json())


if __name__ == "__main__":
    unittest.main()
