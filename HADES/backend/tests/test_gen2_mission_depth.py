"""Gen2 Mission Control + Agent Factory depth toward DoD (B1.2/B1.3/B1.7 + factory extract)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.agent_factory import extract_and_create_candidate, extract_patterns_from_run
from gen2.flight_recorder import record
from gen2.mission_control import (
    ACCEPTANCE_CHECK_TYPES,
    REPLAN_CAUSES,
    compile_mission,
    evaluate_acceptance_checks,
    replan_mission,
    sync_mission_from_task,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class MissionDepthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "depth.db"))
        self.events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            self.events.append(row)
            return row

        self.record = _record
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_compile_attaches_resource_plan_and_acceptance_checks(self) -> None:
        mission = compile_mission(self.store, self.record, "Refactor the coding repo tests")
        ir = mission.get("ir") or {}
        plan = ir.get("resource_plan") or {}
        self.assertEqual(plan.get("source"), "domain_template")
        self.assertIs(plan.get("host_measured"), False)
        self.assertIn("model_slots", plan)
        self.assertIn("estimated_ram_mb", plan)
        self.assertTrue(plan.get("tool_contention_groups"))
        checks = ir.get("acceptance_checks") or []
        self.assertTrue(checks)
        types = {c.get("type") for c in checks}
        self.assertTrue(types <= ACCEPTANCE_CHECK_TYPES)
        self.assertIn("status_equals", types)
        self.assertIn("verification_passed", types)
        self.assertIn("step_completed", types)
        self.assertIn("artifact_exists", types)
        self.assertEqual(ir.get("artifacts"), ["mission_report.md", "evidence_index.json"])
        self.assertTrue(any(c.get("require_all") for c in checks if c.get("type") == "step_completed"))
        # Explicit deliverables are hard gates (A03); presence requires ArtifactService bytes.
        art_checks = [c for c in checks if c.get("type") == "artifact_exists"]
        self.assertTrue(art_checks)
        self.assertTrue(all(c.get("required") is True for c in art_checks))

    def test_acceptance_checks_evaluate_against_evidence_not_prose(self) -> None:
        checks = [
            {"id": "s", "type": "status_equals", "expected": "completed"},
            {"id": "v", "type": "verification_passed"},
            {"id": "a", "type": "artifact_exists", "name": "mission_report.md", "required": True},
            {"id": "t", "type": "step_completed", "step_id": "s_plan"},
        ]
        failed = evaluate_acceptance_checks(
            checks,
            status="completed",
            verification={"status": "pending"},
            step_summary={"total": 1, "completed": 1},
        )
        self.assertFalse(failed["passed"])
        self.assertTrue(any("verification" in b or "artifact" in b or "step" in b for b in failed["blockers"]))

        # Name-only refs must NOT pass required artifact checks (A03).
        name_only = evaluate_acceptance_checks(
            checks,
            status="completed",
            verification={
                "status": "passed",
                "evidence_refs": ["mission_report.md"],
                "artifacts": [{"name": "mission_report.md"}],
            },
            step_summary={
                "total": 1,
                "completed": 1,
                "failed": 0,
                "pending": 0,
                "completed_ids": ["s_plan"],
            },
        )
        self.assertFalse(name_only["passed"])
        self.assertTrue(any("artifact" in b for b in name_only["blockers"]))

        # Without required artifact check, status/verification/steps can still pass.
        no_art = [c for c in checks if c["id"] != "a"]
        passed = evaluate_acceptance_checks(
            no_art,
            status="completed",
            verification={"status": "passed"},
            step_summary={
                "total": 1,
                "completed": 1,
                "failed": 0,
                "pending": 0,
                "completed_ids": ["s_plan"],
            },
        )
        self.assertTrue(passed["passed"])
        self.assertEqual(len(passed["results"]), 3)
        self.assertTrue(all(r["passed"] for r in passed["results"]))

    def test_sync_completion_requires_executable_acceptance(self) -> None:
        mission = compile_mission(self.store, self.record, "Analyse research topic depth")
        step_ids = [
            str(s["id"])
            for w in ((mission.get("ir") or {}).get("execution_waves") or [])
            for s in (w.get("steps") or [])
        ]
        self.store.update_mission(mission["id"], status="running", task_id="task_depth_1")
        # Incomplete step accounting → fail even with verification passed.
        updated = sync_mission_from_task(
            self.store,
            self.record,
            "task_depth_1",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "test",
                "evidence_refs": ["note"],
            },
            step_summary={
                "total": len(step_ids),
                "completed": max(0, len(step_ids) - 1),
                "failed": 0,
                "pending": 1,
                "unknown": 0,
                "skipped": 0,
            },
        )
        assert updated is not None
        self.assertEqual(updated["status"], "failed")
        blockers = ((updated.get("verification") or {}).get("acceptance") or {}).get("blockers") or []
        self.assertTrue(
            any(
                "executable_acceptance" in b
                or "acceptance_check" in b
                or "pending_steps" in b
                or "steps_incomplete" in b
                for b in blockers
            )
        )

        # Required artifact check (explicit) blocks without inventing host files.
        ir = dict(mission.get("ir") or {})
        checks = list(ir.get("acceptance_checks") or [])
        checks.append(
            {
                "id": "ac_required_report",
                "type": "artifact_exists",
                "name": "mission_report.md",
                "required": True,
                "source": "executable",
            }
        )
        ir["acceptance_checks"] = checks
        self.store.update_mission(
            mission["id"],
            status="running",
            task_id="task_depth_art",
            ir=ir,
        )
        missing_art = sync_mission_from_task(
            self.store,
            self.record,
            "task_depth_art",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "test",
                "evidence_refs": ["note"],
            },
            step_summary={
                "total": len(step_ids),
                "completed": len(step_ids),
                "failed": 0,
                "pending": 0,
                "unknown": 0,
                "skipped": 0,
            },
        )
        assert missing_art is not None
        self.assertEqual(missing_art["status"], "failed")

        # Full evidence path still fails when artifacts are name-only (A03).
        self.store.update_mission(mission["id"], status="running", task_id="task_depth_2", ir=ir)
        name_only_ok = sync_mission_from_task(
            self.store,
            self.record,
            "task_depth_2",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "test",
                "evidence_refs": ["mission_report.md", "evidence_index.json"],
                "artifacts": [
                    {"name": "mission_report.md"},
                    {"name": "evidence_index.json"},
                ],
            },
            step_summary={
                "total": len(step_ids),
                "completed": len(step_ids),
                "failed": 0,
                "pending": 0,
                "unknown": 0,
                "skipped": 0,
                "completed_ids": step_ids,
            },
        )
        assert name_only_ok is not None
        self.assertEqual(name_only_ok["status"], "failed")

        # Real ArtifactService bytes → completion allowed.
        from artifacts import ArtifactService
        from database import Database
        from platform_db import PlatformDatabase

        db_path = str(Path(self.temp.name) / "arts.db")
        Database(db_path).initialize()
        pdb = PlatformDatabase(db_path)
        pdb.initialize()
        arts = ArtifactService(pdb, Path(self.temp.name))
        report = arts.create_text_result(
            name="mission_report.md",
            text="# report\nverified\n",
            mime_type="text/markdown",
            kind="generated",
            task_id="task_depth_3",
        )
        index = arts.create_text_result(
            name="evidence_index.json",
            text='{"ok": true}',
            mime_type="application/json",
            kind="generated",
            task_id="task_depth_3",
        )
        self.store.update_mission(mission["id"], status="running", task_id="task_depth_3", ir=ir)
        ok = sync_mission_from_task(
            self.store,
            self.record,
            "task_depth_3",
            status="completed",
            verification={
                "status": "passed",
                "required": True,
                "source": "test",
                "evidence_refs": [report["id"], index["id"]],
                "artifacts": [report, index],
                "task_id": "task_depth_3",
            },
            step_summary={
                "total": len(step_ids),
                "completed": len(step_ids),
                "failed": 0,
                "pending": 0,
                "unknown": 0,
                "skipped": 0,
                "completed_ids": step_ids,
            },
            artifact_service=arts,
        )
        assert ok is not None
        self.assertEqual(ok["status"], "completed")
        self.assertTrue((ok.get("verification") or {}).get("acceptance_checks_eval", {}).get("passed"))

    def test_replan_cause_taxonomy_and_max_replans(self) -> None:
        mission = compile_mission(self.store, self.record, "Research bounded replan")
        self.store.update_mission(mission["id"], status="blocked", error="tool_failed")
        self.assertEqual(REPLAN_CAUSES, {"tool", "model", "verification", "budget", "permission", "schema"})
        with self.assertRaises(ValueError):
            replan_mission(self.store, self.record, mission["id"], "magic")
        first = replan_mission(self.store, self.record, mission["id"], "tool", note="retry tool")
        self.assertEqual(first["replan_count"], 1)
        self.assertIn(first["status"], {"ready", "awaiting_approval", "blocked"})
        self.assertTrue(any(e["event_type"] == "REPLAN" for e in self.events))
        # Tool replan must alter execution waves (contentful), not only bump counters.
        old_waves = (mission.get("ir") or {}).get("execution_waves") or []
        new_waves = (first.get("ir") or {}).get("execution_waves") or []
        self.assertNotEqual(old_waves, new_waves)
        self.assertEqual(first.get("replan_kind"), "contentful")
        # Exhaust budget.
        self.store.update_mission(
            mission["id"],
            status="failed",
            budgets={**(mission.get("budgets") or {}), "max_replans": 2, "replan_count": 1},
            ir={**(first.get("ir") or mission.get("ir") or {}), "replan_count": 1},
        )
        replan_mission(self.store, self.record, mission["id"], "verification")
        with self.assertRaises(ValueError) as ctx:
            # After second replan, count=2 == max → next fails.
            m = self.store.get_mission(mission["id"])
            assert m is not None
            # Force count back to max for enforcement check.
            self.store.update_mission(
                mission["id"],
                status="blocked",
                budgets={**(m.get("budgets") or {}), "max_replans": 2, "replan_count": 2},
                ir={**(m.get("ir") or {}), "replan_count": 2},
            )
            replan_mission(self.store, self.record, mission["id"], "budget")
        self.assertIn("max_replans_exceeded", str(ctx.exception))

    def test_services_acceptance_and_replan(self) -> None:
        mission = self.svc.compile_mission("Finance NVIDIA earnings depth")
        ir = mission.get("ir") or {}
        self.assertFalse((ir.get("resource_plan") or {}).get("host_measured"))
        evaled = self.svc.evaluate_mission_acceptance(
            mission["id"],
            status="completed",
            verification={"status": "passed", "artifacts": [{"name": "mission_report.md"}]},
            step_summary={"completed_ids": ["s_scope"], "total": 1, "completed": 1, "failed": 0, "pending": 0},
        )
        self.assertIn("results", evaled)
        self.store.update_mission(mission["id"], status="blocked")
        before_waves = (mission.get("ir") or {}).get("execution_waves")
        replanned = self.svc.replan_mission(mission["id"], "model", note="swap planner")
        self.assertEqual(replanned["replan_count"], 1)
        self.assertEqual(replanned.get("replan_kind"), "contentful")
        self.assertNotEqual(before_waves, (replanned.get("ir") or {}).get("execution_waves"))

    def test_permission_replan_does_not_swap_tools(self) -> None:
        mission = compile_mission(self.store, self.record, "Refactor coding tool permission")
        self.store.update_mission(mission["id"], status="blocked", error="permission denied: terminal")
        before = {
            str(s["id"]): list(s.get("tools") or [])
            for w in ((mission.get("ir") or {}).get("execution_waves") or [])
            for s in (w.get("steps") or [])
        }
        out = replan_mission(
            self.store,
            self.record,
            mission["id"],
            "permission",
            note="terminal denied",
            failed_step_id="s_build",
        )
        after = {
            str(s["id"]): list(s.get("tools") or [])
            for w in ((out.get("ir") or {}).get("execution_waves") or [])
            for s in (w.get("steps") or [])
        }
        self.assertEqual(before, after)
        self.assertIn(out["status"], {"blocked", "awaiting_approval"})
        self.assertEqual(out.get("replan_kind"), "identical_retry")
        reason = f"{out.get('error') or ''} {out.get('operational_reason') or ''}".lower()
        self.assertTrue("permission" in reason or "denied" in reason or "approval" in reason)


class AgentFactoryExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "factory.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_empty_run_does_not_create_candidate_or_promote(self) -> None:
        extracted = extract_patterns_from_run(self.store, "run_empty")
        self.assertFalse(extracted["createable"])
        self.assertEqual(extracted["reason"], "empty_run")
        result = extract_and_create_candidate(self.store, self.svc.record, "run_empty")
        self.assertFalse(result["created"])
        self.assertIsNone(result["skill"])
        self.assertEqual(self.store.list_skills(), [])

    def test_failed_run_does_not_create_promoted_skill(self) -> None:
        run_id = "run_failed_tools"
        record(
            self.store,
            run_id,
            "TOOL",
            {"action": "echo", "inputs": {"message": "x"}, "ok": False, "error": "boom"},
            component="test",
        )
        record(
            self.store,
            run_id,
            "VERIFY",
            {"passed": False, "status": "failed"},
            component="test",
        )
        record(self.store, run_id, "RUN_FAILED", {"status": "failed"}, component="test")
        result = self.svc.extract_and_create_candidate(run_id, name="should-not-create")
        self.assertFalse(result["created"])
        self.assertFalse(result.get("promoted"))
        self.assertEqual(self.store.list_skills(), [])

    def test_successful_handler_trace_creates_candidate_not_promoted(self) -> None:
        run_id = "run_ok_echo"
        record(
            self.store,
            run_id,
            "TOOL",
            {"action": "echo", "inputs": {"message": "hello"}, "ok": True},
            component="test",
        )
        record(
            self.store,
            run_id,
            "TOOL",
            {"action": "assert_nonempty", "inputs": {"value": "hello"}, "ok": True},
            component="test",
        )
        record(
            self.store,
            run_id,
            "VERIFY",
            {"passed": True, "status": "passed"},
            component="test",
        )
        record(self.store, run_id, "RUN_COMPLETED", {"status": "completed", "passed": True}, component="test")
        patterns = extract_patterns_from_run(self.store, run_id)
        self.assertTrue(patterns["createable"])
        self.assertTrue(patterns["known_handlers_only"])
        actions = [s["action"] for s in patterns["proposed_workflow"]]
        self.assertEqual(actions, ["echo", "assert_nonempty"])
        # Free-text / unknown handlers must not appear.
        self.assertNotIn("do something clever", actions)

        result = extract_and_create_candidate(
            self.store, self.svc.record, run_id, name="echo-from-run"
        )
        self.assertTrue(result["created"])
        self.assertFalse(result.get("promoted"))
        skill = result["skill"]
        assert skill is not None
        self.assertEqual(skill["status"], "candidate")
        self.assertEqual(skill["name"], "echo-from-run")
        workflow = (skill.get("definition") or {}).get("workflow") or []
        self.assertEqual([w.get("action") for w in workflow], ["echo", "assert_nonempty"])

    def test_unknown_tool_actions_not_invented_as_handlers(self) -> None:
        run_id = "run_unknown"
        record(
            self.store,
            run_id,
            "TOOL",
            {"action": "nvidia_secret_sauce", "ok": True},
            component="test",
        )
        record(self.store, run_id, "VERIFY", {"passed": True, "status": "passed"}, component="test")
        extracted = extract_patterns_from_run(self.store, run_id)
        self.assertFalse(extracted["createable"])
        self.assertIn("nvidia_secret_sauce", extracted.get("unknown_tool_actions") or [])
        self.assertEqual(extracted["proposed_workflow"], [])


if __name__ == "__main__":
    unittest.main()
