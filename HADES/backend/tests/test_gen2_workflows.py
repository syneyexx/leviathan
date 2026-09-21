"""Comprehensive tests for Gen2 Workflows product (A5 / B2.1–B2.11)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.dashboard import build_dashboard
from gen2.services import Gen2Services
from gen2.store import Gen2Store
from gen2.workflows import (
    TEMPLATE_LIBRARY,
    create_from_template,
    create_workflow,
    decide_human_step,
    diff_revisions,
    draft_from_nl,
    dry_run,
    export_workflow,
    import_workflow,
    list_templates,
    promote_workflow,
    sandbox_run,
    update_workflow,
    validate_workflow,
    workflow_to_skill_candidate,
)


class WorkflowModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "workflows.db"))
        self.events: list[str] = []

        def _record(run_id: str, event_type: str, payload=None, **kwargs):
            self.events.append(event_type)
            return {"run_id": run_id, "event_type": event_type}

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validate_catches_cycles_and_missing_ids(self) -> None:
        cycle = {
            "name": "cyclic",
            "status": "draft",
            "steps": [
                {"id": "a", "type": "action", "action": "echo", "inputs": {"message": "a"}, "depends_on": ["b"]},
                {"id": "b", "type": "action", "action": "echo", "inputs": {"message": "b"}, "depends_on": ["a"]},
            ],
            "offline_safe": True,
            "permissions": {"network": "deny"},
        }
        errors = validate_workflow(cycle)
        self.assertTrue(any("cycle" in e for e in errors), errors)

        missing = {
            "name": "missing-dep",
            "status": "draft",
            "steps": [
                {"id": "a", "type": "action", "action": "echo", "inputs": {"message": "a"}, "depends_on": ["ghost"]},
            ],
            "offline_safe": True,
            "permissions": {"network": "deny"},
        }
        errors2 = validate_workflow(missing)
        self.assertTrue(any("unknown:ghost" in e for e in errors2), errors2)

        no_id = {
            "name": "no-id",
            "status": "draft",
            "steps": [{"type": "action", "action": "echo", "inputs": {"message": "x"}}],
        }
        errors3 = validate_workflow(no_id)
        self.assertTrue(any("missing id" in e for e in errors3), errors3)

    def test_template_library_creates_valid_ir(self) -> None:
        templates = list_templates()
        self.assertGreaterEqual(len(templates), 5)
        for key, factory in TEMPLATE_LIBRARY.items():
            ir = factory()
            errors = validate_workflow(ir)
            self.assertEqual(errors, [], f"{key} invalid: {errors}")
            self.assertEqual(ir.get("draft_source"), "template")
            row = create_from_template(self.store, self.record, key)
            self.assertEqual(row["status"], "draft")
            self.assertFalse(validate_workflow(row["definition"]))

    def test_nl_draft_without_lm_is_deterministic_and_labeled(self) -> None:
        a = draft_from_nl("research NVIDIA earnings evidence")
        b = draft_from_nl("research NVIDIA earnings evidence")
        self.assertEqual(a.get("draft_source"), "nl_deterministic")
        self.assertEqual(b.get("draft_source"), "nl_deterministic")
        self.assertEqual(a["steps"][0]["inputs"], b["steps"][0]["inputs"])
        self.assertEqual(validate_workflow(a), [])

        coding = draft_from_nl("implement coding refactor for the patch")
        self.assertIn("coding", (coding.get("name") or "").lower() + str(coding.get("pattern_tags")))
        ingest = draft_from_nl("ingest local files into knowledge")
        self.assertIn("ingest", str(ingest.get("pattern_tags")))
        eval_draft = draft_from_nl("run eval benchmark quality suite")
        self.assertIn("eval", str(eval_draft.get("pattern_tags")))
        paper = draft_from_nl("paper trade study for mean reversion")
        self.assertIn("paper", str(paper.get("pattern_tags")) + (paper.get("name") or ""))

        def _chat(_prompt: str) -> str:
            return json.dumps(
                {
                    "name": "lm-draft",
                    "description": "from lm",
                    "steps": [
                        {
                            "id": "s1",
                            "type": "action",
                            "action": "echo",
                            "inputs": {"message": "hi"},
                            "depends_on": [],
                        }
                    ],
                    "offline_safe": True,
                    "permissions": {"network": "deny"},
                    "success_checks": ["all_steps_passed"],
                }
            )

        lm = draft_from_nl("anything", chat_fn=_chat)
        self.assertEqual(lm.get("draft_source"), "nl_lm")
        self.assertEqual(lm.get("name"), "lm-draft")

    def test_dry_run_vs_sandbox_run(self) -> None:
        row = create_from_template(self.store, self.record, "coding_demo")
        dry = dry_run(self.store, self.record, row["id"])
        self.assertEqual(dry["mode"], "dry_run")
        self.assertFalse(dry["live_execution"])
        self.assertFalse(dry["side_effects"])
        self.assertTrue(dry["passed"])
        self.assertIn("plan", dry)
        self.assertTrue(dry["plan"]["step_order"])

        sand = sandbox_run(self.store, self.record, row["id"])
        self.assertEqual(sand["mode"], "sandbox")
        self.assertFalse(sand["live_execution"])
        self.assertFalse(sand.get("product_ready"))
        self.assertTrue(sand["passed"])
        self.assertTrue(any(s.get("executed") for s in sand["step_results"]))
        # Dry-run must not claim handler execution.
        self.assertNotIn("step_results", dry)
        usage = (sand.get("metrics") or {}).get("usage") or {}
        self.assertEqual(usage.get("source"), "not_measured")
        self.assertIsNone((sand.get("metrics") or {}).get("cost_tokens"))

    def test_promote_requires_tested_and_human_approved(self) -> None:
        row = create_from_template(self.store, self.record, "coding_demo", name="promo-coding")
        with self.assertRaises(ValueError):
            promote_workflow(self.store, self.record, row["id"], target="tested")

        dry_run(self.store, self.record, row["id"])
        tested = promote_workflow(self.store, self.record, row["id"], target="tested")
        self.assertEqual(tested["status"], "tested")

        with self.assertRaises(ValueError):
            promote_workflow(self.store, self.record, row["id"], human_approved=False, target="promoted")

        promoted = promote_workflow(
            self.store, self.record, row["id"], human_approved=True, target="promoted"
        )
        self.assertEqual(promoted["status"], "promoted")

        # Broken workflow fails promote.
        broken = create_workflow(
            self.store,
            self.record,
            {
                "name": "ok-then-break",
                "steps": [
                    {"id": "a", "type": "action", "action": "echo", "inputs": {"message": "x"}, "depends_on": []},
                ],
                "offline_safe": True,
                "permissions": {"network": "deny"},
                "success_checks": ["all_steps_passed"],
                "fixture_kind": "heritage_demo",
                "pattern_tags": ["heritage", "demo"],
            },
        )
        # Corrupt definition directly in store (bypass validate).
        bad_def = dict(broken["definition"])
        bad_def["steps"] = [
            {"id": "a", "type": "action", "action": "echo", "inputs": {"message": "x"}, "depends_on": ["missing"]},
        ]
        self.store.update_workflow(broken["id"], definition=bad_def)
        with self.assertRaises(ValueError):
            promote_workflow(self.store, self.record, broken["id"], target="tested")

    def test_import_export_roundtrip(self) -> None:
        row = create_from_template(self.store, self.record, "ingest", name="ingest-roundtrip")
        package = export_workflow(self.store, row["id"], as_zip=False)
        self.assertIsInstance(package, dict)
        self.assertEqual(package["format"], "HadesWorkflow")
        self.assertEqual(package["format_version"], 1)
        self.assertIn("definition", package)
        self.assertIn("metadata", package)

        imported = import_workflow(self.store, self.record, package)
        self.assertEqual(imported["status"], "draft")
        self.assertEqual(validate_workflow(imported["definition"]), [])
        self.assertNotEqual(imported["id"], row["id"])

        zipped = export_workflow(self.store, row["id"], as_zip=True)
        self.assertIsInstance(zipped, (bytes, bytearray))
        imported_zip = import_workflow(self.store, self.record, zipped)
        self.assertEqual(imported_zip["status"], "draft")

        with self.assertRaises(ValueError):
            import_workflow(self.store, self.record, {"format": "Nope", "format_version": 1, "definition": {}})

    def test_revision_diff(self) -> None:
        row = create_from_template(self.store, self.record, "eval", name="diff-eval")
        v1 = int(row.get("version") or 1)
        updated = update_workflow(
            self.store,
            self.record,
            row["id"],
            {
                **(row.get("definition") or {}),
                "description": "updated description for diff",
            },
            note="desc bump",
        )
        v2 = int(updated.get("version") or 2)
        self.assertGreater(v2, v1)
        diff = diff_revisions(self.store, row["id"], v1, v2)
        self.assertEqual(diff["from_version"], v1)
        self.assertEqual(diff["to_version"], v2)
        self.assertGreaterEqual(diff["change_count"], 1)
        paths = [c["path"] for c in diff["changes"]]
        self.assertTrue(any(p == "description" or p.startswith("steps.") for p in paths), diff)

    def test_to_skill_creates_candidate(self) -> None:
        row = create_from_template(self.store, self.record, "coding_demo", name="bridge-coding")
        skill = workflow_to_skill_candidate(self.store, self.record, row["id"])
        self.assertEqual(skill["status"], "candidate")
        definition = skill.get("definition") or {}
        self.assertEqual(definition.get("pattern_source"), f"workflow:{row['id']}")
        self.assertTrue(definition.get("workflow"))
        refreshed = self.store.get_workflow(row["id"])
        self.assertEqual((refreshed.get("definition") or {}).get("skill_candidate_id"), skill["id"])

    def test_hitl_step_pauses(self) -> None:
        row = create_from_template(self.store, self.record, "research_demo", name="hitl-research")
        sand = sandbox_run(self.store, self.record, row["id"])
        self.assertEqual(sand["status"], "awaiting_human")
        self.assertFalse(sand["passed"])
        self.assertIsNotNone(sand.get("awaiting_human"))
        self.assertEqual(sand["awaiting_human"]["step_id"], "approve_publish")
        self.assertEqual(sand["awaiting_human"]["type"], "approve")

        decided = decide_human_step(
            self.store,
            self.record,
            row["id"],
            "approve_publish",
            decision="approve",
            resume=True,
        )
        self.assertEqual(decided["status"], "resolved")
        self.assertTrue((self.store.get_workflow(row["id"]).get("definition") or {}).get("human_approved"))

    def test_services_and_dashboard_wire(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        drafted = svc.draft_workflow("coding demo implement feature X")
        self.assertEqual(drafted.get("draft_source"), "nl_deterministic")
        created = svc.create_workflow_from_template("coding_demo")
        dry = svc.dry_run_workflow(created["id"])
        self.assertTrue(dry["passed"])
        self.assertFalse(dry["live_execution"])
        sand = svc.sandbox_run_workflow(created["id"])
        self.assertIn(sand["status"], {"passed", "completed", "awaiting_human", "failed"})
        dash = build_dashboard(self.store, data_root=Path(self.temp.name))
        self.assertIn("2_workflows", dash["capability_status"])
        self.assertTrue(dash["capability_status"]["2_workflows"]["implemented"])
        self.assertTrue(dash["capability_status"]["2_workflows"]["available_on_host"])
        self.assertIn("workflows", dash)
        # Not operationally_tested until tested/promoted status exists.
        self.assertFalse(dash["capability_status"]["2_workflows"]["operationally_tested"])

        svc.promote_workflow(created["id"], target="tested")
        dash2 = build_dashboard(self.store, data_root=Path(self.temp.name))
        self.assertTrue(dash2["capability_status"]["2_workflows"]["operationally_tested"])

    def test_metrics_from_runs(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        row = svc.create_workflow_from_template("coding_demo")
        svc.sandbox_run_workflow(row["id"])
        metrics = svc.workflow_metrics(row["id"])
        self.assertIn("success_rate", metrics["metrics"])
        self.assertIn("latency_ms", metrics["metrics"])
        self.assertIn("tool_failures", metrics["metrics"])
        self.assertIn("cost_tokens", metrics["metrics"])
        self.assertGreaterEqual(metrics["metrics"]["run_count"], 1)
        self.assertIsNone(metrics["metrics"]["cost_tokens"])


if __name__ == "__main__":
    unittest.main()
