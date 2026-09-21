"""Focused regressions for A07 — contentful mission replan with wave diffs."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.mission_control import (
    compile_mission,
    rebuild_execution_waves_for_replan,
    replan_mission,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class A07ContentfulReplanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "a07.db"))
        self.events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            self.events.append(row)
            return row

        self.record = _record
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_tool_replan_swaps_to_alternate_tool(self) -> None:
        mission = compile_mission(self.store, self.record, "Finance NVIDIA earnings depth")
        self.store.update_mission(
            mission["id"],
            status="blocked",
            verification={
                "status": "failed",
                "step_summary": {
                    "completed_ids": ["s_scope"],
                    "failed_ids": ["s_sources"],
                    "total": 6,
                    "completed": 1,
                    "failed": 1,
                },
            },
        )
        mission = self.store.get_mission(mission["id"])
        assert mission is not None
        before_tools = None
        for wave in (mission.get("ir") or {}).get("execution_waves") or []:
            for step in wave.get("steps") or []:
                if step.get("id") == "s_sources":
                    before_tools = list(step.get("tools") or [])
        self.assertEqual(before_tools, ["financial-news-intelligence"])

        out = replan_mission(
            self.store,
            self.record,
            mission["id"],
            "tool",
            note="news plugin failed",
            failed_step_id="s_sources",
        )
        self.assertEqual(out["replan_kind"], "contentful")
        self.assertFalse(out.get("no_valid_alternative"))
        after_tools = None
        for wave in (out.get("ir") or {}).get("execution_waves") or []:
            for step in wave.get("steps") or []:
                if step.get("id") == "s_sources":
                    after_tools = list(step.get("tools") or [])
                    self.assertEqual(step.get("replan_action"), "alternate_tool")
        self.assertIsNotNone(after_tools)
        self.assertNotEqual(before_tools, after_tools)
        self.assertEqual(out["plan_version_after"], out["plan_version_before"] + 1)
        self.assertTrue(out.get("changed_steps"))
        self.assertIn("s_scope", (out.get("ir") or {}).get("last_replan_diff", {}).get("preserved_step_ids") or [])
        # Wave diff persisted on revision path via verification + ir.
        self.assertEqual((out.get("verification") or {}).get("last_replan_kind"), "contentful")
        payload = next(e["payload"] for e in self.events if e["event_type"] == "REPLAN")
        self.assertEqual(payload.get("replan_kind"), "contentful")
        self.assertIn("operational_reason", payload)

    def test_permission_replan_blocks_without_tool_swap(self) -> None:
        mission = compile_mission(self.store, self.record, "Refactor coding repo tests")
        self.store.update_mission(mission["id"], status="blocked", error="permission denied")
        before = (mission.get("ir") or {}).get("execution_waves")
        out = replan_mission(
            self.store,
            self.record,
            mission["id"],
            "permission",
            note="terminal not approved",
            failed_step_id="s_build",
        )
        self.assertEqual(out.get("replan_kind"), "identical_retry")
        self.assertEqual((out.get("ir") or {}).get("execution_waves"), before)
        after_build_tools = None
        for wave in (out.get("ir") or {}).get("execution_waves") or []:
            for step in wave.get("steps") or []:
                if step.get("id") == "s_build":
                    after_build_tools = list(step.get("tools") or [])
        self.assertEqual(after_build_tools, ["terminal"])
        self.assertIn(out["status"], {"blocked", "awaiting_approval"})
        self.assertTrue(out.get("error") or out.get("operational_reason"))

    def test_max_replans_zero_is_respected(self) -> None:
        mission = compile_mission(self.store, self.record, "Research zero replans")
        self.store.update_mission(
            mission["id"],
            status="blocked",
            budgets={**(mission.get("budgets") or {}), "max_replans": 0, "replan_count": 0},
            ir={
                **(mission.get("ir") or {}),
                "retry_policies": {
                    **((mission.get("ir") or {}).get("retry_policies") or {}),
                    "max_replans": 0,
                },
            },
        )
        with self.assertRaises(ValueError) as ctx:
            replan_mission(self.store, self.record, mission["id"], "tool")
        self.assertIn("max_replans_exceeded", str(ctx.exception))

    def test_verification_replan_appends_repair_wave(self) -> None:
        mission = compile_mission(self.store, self.record, "Research verification repair")
        self.store.update_mission(
            mission["id"],
            status="blocked",
            verification={
                "status": "failed",
                "acceptance_checks_eval": {
                    "passed": False,
                    "results": [{"id": "ac_verification_passed", "passed": False}],
                },
                "step_summary": {"completed_ids": ["s_scope", "s_retrieve"], "failed": 0},
            },
        )
        mission = self.store.get_mission(mission["id"])
        assert mission is not None
        before_count = sum(
            len(w.get("steps") or []) for w in ((mission.get("ir") or {}).get("execution_waves") or [])
        )
        out = replan_mission(self.store, self.record, mission["id"], "verification", note="critic failed")
        after_waves = (out.get("ir") or {}).get("execution_waves") or []
        after_count = sum(len(w.get("steps") or []) for w in after_waves)
        self.assertGreater(after_count, before_count)
        self.assertEqual(out["replan_kind"], "contentful")
        ids = [s.get("id") for w in after_waves for s in (w.get("steps") or [])]
        self.assertTrue(any(str(i).startswith("s_repair_verify") for i in ids))

    def test_rebuild_helper_schema_and_budget(self) -> None:
        mission = compile_mission(self.store, self.record, "Research schema and budget")
        schema = rebuild_execution_waves_for_replan(
            mission, "schema", "bad json", failed_step_id="s_research"
        )
        self.assertEqual(schema["replan_kind"], "contentful")
        self.assertTrue(any(c["step_id"].endswith("schema_repair") for c in schema["changed_steps"]))

        budget = rebuild_execution_waves_for_replan(mission, "budget", "overspent")
        self.assertEqual(budget["replan_kind"], "contentful")
        # Optional knowledge/archive step dropped on research template.
        after_ids = {
            str(s.get("id"))
            for w in budget["waves"]
            for s in (w.get("steps") or [])
        }
        self.assertNotIn("s_archive", after_ids)

    def test_services_replan_passes_failed_step_id(self) -> None:
        mission = self.svc.compile_mission("Finance NVIDIA earnings depth")
        self.store.update_mission(mission["id"], status="blocked")
        out = self.svc.replan_mission(
            mission["id"], "tool", note="swap", failed_step_id="s_market"
        )
        self.assertEqual(out["replan_kind"], "contentful")
        for wave in (out.get("ir") or {}).get("execution_waves") or []:
            for step in wave.get("steps") or []:
                if step.get("id") == "s_market":
                    self.assertNotEqual(list(step.get("tools") or []), ["trading"])
                    return
        self.fail("s_market not found after replan")

    def test_changed_actions_do_not_inherit_stale_approvals(self) -> None:
        mission = compile_mission(self.store, self.record, "Refactor coding repo tests")
        gates = list(mission.get("gates") or [])
        for g in gates:
            g["status"] = "approved"
            g["approval_scope"] = "stale_scope_token"
        self.store.update_mission(mission["id"], status="blocked", gates=gates)
        out = replan_mission(
            self.store,
            self.record,
            mission["id"],
            "tool",
            note="terminal failed",
            failed_step_id="s_build",
        )
        self.assertEqual(out["replan_kind"], "contentful")
        invalidated = (out.get("wave_diff") or {}).get("invalidated_approvals") or []
        self.assertTrue(invalidated)
        live = self.store.get_mission(mission["id"])
        assert live is not None
        pending = [g for g in (live.get("gates") or []) if g.get("status") == "pending"]
        self.assertTrue(pending)


if __name__ == "__main__":
    unittest.main()
