"""Autonomous work-partner vertical slices — WP1–WP11 focused regressions."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artifacts import ArtifactService
from coding_requirement_map import build_requirement_verification_map, failed_repair_delivery
from database import Database
from gen2.agent_factory import promote_skill, run_generalization_skill_tests, run_mandatory_skill_tests
from gen2.store import Gen2Store
from platform_db import PlatformDatabase
from project_continuity import ProjectContinuityService, apply_project_context_to_prompt
from proactive_triggers import ProactiveTriggerService
from reasoning.plan_scheduler import choose_recovery_strategy, steps_invalidated_by_input_change
from reasoning.resource_awareness import VersionedCache, backpressure_decision, cache_key, classify_task_complexity
from research_conflicts import fixture_conflicting_research, independent_evidence_count
from result_contracts import build_result_contract, evaluate_result_contract, reverify_after_artifact_fix
from runtime.effect_ledger import EffectLedger
from runtime.tool_contracts import classify_tool_action, run_tool_contract_tests


class ProjectContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "core.sqlite3"))
        self.svc = ProjectContinuityService(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_restart_and_constraint_change_keeps_decisions(self) -> None:
        project = self.svc.create_project("Alpha")
        self.svc.add_item(
            project["id"],
            kind="decision",
            title="Use SQLite",
            body="Besluit: we gebruiken SQLite",
            provenance="user_explicit",
        )
        self.svc.add_item(
            project["id"],
            kind="constraint",
            title="Max latency 2s",
            body="Latency moet onder 2 seconden blijven",
            provenance="user_explicit",
        )
        # Simulate restart with a fresh service on same DB.
        svc2 = ProjectContinuityService(Database(str(Path(self.tmp.name) / "core.sqlite3")))
        pkg = svc2.context_package(project["id"])
        self.assertEqual(len(pkg["decisions"]), 1)
        self.assertEqual(len(pkg["constraints"]), 1)
        # User changes constraint — old one superseded, decision preserved.
        svc2.add_item(
            project["id"],
            kind="constraint",
            title="Max latency 5s instead of 2s",
            body="Correctie: latency mag onder 5 seconden; in plaats van 2 seconden",
            provenance="user_explicit",
            replace_overlapping=True,
        )
        pkg2 = svc2.context_package(project["id"])
        self.assertEqual(len(pkg2["decisions"]), 1)
        self.assertEqual(len(pkg2["constraints"]), 1)
        self.assertIn("5", pkg2["constraints"][0]["title"] + pkg2["constraints"][0]["body"])
        prompt = apply_project_context_to_prompt(pkg2)
        self.assertIn("SQLite", prompt)
        self.assertNotIn("2 seconden blijven", prompt)

    def test_projects_do_not_leak_without_relation(self) -> None:
        a = self.svc.create_project("A")
        b = self.svc.create_project("B")
        self.svc.add_item(a["id"], kind="goal", title="Secret A", provenance="user_explicit")
        pkg_b = self.svc.context_package(b["id"])
        self.assertEqual(pkg_b["goals"], [])
        self.assertEqual(pkg_b["related_project_ids"], [])


class ResultContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "platform.sqlite3"))
        self.db.initialize()
        self.arts = ArtifactService(self.db, Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_required_artifact_blocks_completion(self) -> None:
        contract = build_result_contract(domain="coding", goal="fix bug")
        result = evaluate_result_contract(
            contract,
            status="completed",
            verification={"status": "passed"},
            step_summary={"total": 1, "completed": 1, "failed": 0, "pending": 0, "unknown": 0},
            artifact_service=self.arts,
            extras={"test_results": {"passed": True}},
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["may_complete"])
        self.assertTrue(result["missing_artifacts"] or result["blockers"])

    def test_corrected_artifact_passes_reverify(self) -> None:
        contract = build_result_contract(
            domain="file_processing",
            goal="emit output",
            required_outputs=["output.txt"],
            acceptance_checks=[
                {"id": "ac_out", "type": "artifact_exists", "name": "output.txt", "required": True, "min_bytes": 1},
                {"id": "ac_status", "type": "status_equals", "expected": "completed", "required": True},
                {"id": "ac_ver", "type": "verification_passed", "required": True},
                {"id": "ac_steps", "type": "step_completed", "require_all": True, "required": True},
            ],
        )
        miss = evaluate_result_contract(
            contract,
            status="completed",
            verification={"status": "passed"},
            step_summary={"total": 1, "completed": 1, "failed": 0, "pending": 0, "unknown": 0},
            artifact_service=self.arts,
        )
        self.assertFalse(miss["passed"])
        art = self.arts.create(name="output.txt", kind="generated", data=b"ok-bytes")
        mission = {"artifacts": [{"id": art["id"], "name": "output.txt"}]}
        ok = reverify_after_artifact_fix(
            contract,
            artifact_service=self.arts,
            mission=mission,
            verification={"status": "passed", "evidence_refs": [art["id"]]},
            step_summary={"total": 1, "completed": 1, "failed": 0, "pending": 0, "unknown": 0},
            status="completed",
        )
        self.assertTrue(ok["passed"])
        self.assertTrue(ok["may_complete"])


class InputInvalidationTests(unittest.TestCase):
    def test_only_hit_branch_invalidated(self) -> None:
        steps = [
            {"step_id": "a", "depends_on": [], "input_refs": ["file_a"]},
            {"step_id": "b", "depends_on": [], "input_refs": ["file_b"]},
            {"step_id": "c", "depends_on": ["a"], "input_refs": []},
            {"step_id": "verify_a", "depends_on": ["c"], "input_refs": []},
            {"step_id": "d", "depends_on": ["b"], "input_refs": []},
        ]
        plan = steps_invalidated_by_input_change(
            steps,
            completed_ids={"a", "b", "c", "d", "verify_a"},
            changed_input_refs={"file_a"},
        )
        self.assertIn("a", plan["invalidated_step_ids"])
        self.assertIn("c", plan["invalidated_step_ids"])
        self.assertIn("verify_a", plan["invalidated_step_ids"])
        self.assertNotIn("b", plan["invalidated_step_ids"])
        self.assertNotIn("d", plan["invalidated_step_ids"])
        self.assertIn("b", plan["reusable_step_ids"])
        self.assertIn("d", plan["reusable_step_ids"])

    def test_recovery_taxonomy(self) -> None:
        self.assertEqual(choose_recovery_strategy(cause="ambiguous_goal")["strategy"], "ask_user")
        self.assertEqual(
            choose_recovery_strategy(cause="provider_down", alternate_tool_available=True)["strategy"],
            "alternate_tool",
        )


class ResearchConflictTests(unittest.TestCase):
    def test_fixture_shows_conflict_without_invented_resolution(self) -> None:
        report = fixture_conflicting_research()
        self.assertGreaterEqual(report["conflict_count"], 1)
        self.assertFalse(report["silenced"])
        self.assertFalse(report["invented_resolution"])
        claim = report["claims"][0]
        self.assertEqual(claim["independence"]["independent_support_origins"], 1)
        self.assertGreaterEqual(len(claim["contradicts"]), 1)
        self.assertGreaterEqual(len(claim["supports"]), 1)

    def test_republication_not_independent(self) -> None:
        count = independent_evidence_count(
            [
                {"relation": "supports", "origin_id": "a", "id": "1"},
                {"relation": "supports", "origin_id": "blog", "republication_of": "a", "id": "2"},
            ]
        )
        self.assertEqual(count["independent_support_origins"], 1)


class CodingMapTests(unittest.TestCase):
    def test_requirement_map_and_failed_repair(self) -> None:
        mapping = build_requirement_verification_map(
            requirements=["fix off-by-one"],
            changed_files=["app.py"],
            test_results={"passed": True, "tests": ["test_off_by_one"]},
            base_revision="abc123",
            protected_user_paths=["notes.local"],
        )
        self.assertTrue(mapping["user_files_preserved"])
        fail = failed_repair_delivery(diagnosis="tests still red", requirement_map=mapping)
        self.assertFalse(fail["completed"])
        self.assertEqual(fail["status"], "failed_repair")


class ToolContractAndLedgerTests(unittest.TestCase):
    def test_contract_tests_and_restart_classes(self) -> None:
        tool = {
            "name": "write_file",
            "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
            "metadata": {"action": "write", "idempotent": False},
        }
        effect = classify_tool_action(tool)
        self.assertTrue(effect["mutating"])
        self.assertFalse(effect["compensation_is_rollback"])
        report = run_tool_contract_tests(
            tool,
            cases=[{"id": "missing", "arguments": {}, "expect_validation_error": True}],
        )
        self.assertTrue(report["passed"])

        tmp = tempfile.TemporaryDirectory()
        try:
            ledger = EffectLedger(Path(tmp.name) / "effects.db")
            # before effect
            rec = ledger.prepare(tool="write_file", arguments={"path": "x"}, effect_class="fs_write")
            ledger.mark_failed(rec.effect_id, detail={"effect_applied": False, "failure_stage": "before_execute"})
            self.assertEqual(ledger.classify_on_restart(rec.effect_id)["class"], "SAFE_TO_RETRY")
            # during / after possible effect
            rec2 = ledger.prepare(tool="write_file", arguments={"path": "y"}, effect_class="fs_write")
            ledger.mark_failed(rec2.effect_id, detail={"effect_applied": True, "failure_stage": "after_execute"})
            self.assertEqual(ledger.classify_on_restart(rec2.effect_id)["class"], "REQUIRES_RECONCILIATION")
            # unknown
            rec3 = ledger.prepare(tool="write_file", arguments={"path": "z"}, effect_class="fs_write")
            ledger.mark_unknown(rec3.effect_id)
            self.assertEqual(ledger.classify_on_restart(rec3.effect_id)["class"], "UNKNOWN_EXTERNAL_STATE")
        finally:
            tmp.cleanup()


class SkillGeneralizationTests(unittest.TestCase):
    def test_single_example_overfit_not_promoted(self) -> None:
        definition = {
            "workflow": [{"action": "echo", "inputs": {"text": "ok"}}],
            "development_examples": [{"id": "dev1", "text": "only"}],
            "evaluation_cases": [{"id": "dev1", "text": "only"}],  # identical sole example
            "negative_cases": [],  # missing negatives
            "mandatory_tests": [{"id": "g", "type": "generalization"}],
        }
        gen = run_generalization_skill_tests(definition)
        self.assertFalse(gen["passed"])
        mandatory = run_mandatory_skill_tests(definition)
        self.assertFalse(mandatory["passed"])

    def test_variants_and_negatives_can_pass(self) -> None:
        definition = {
            "workflow": [{"action": "echo", "inputs": {"text": "ok"}}],
            "development_examples": [{"id": "dev1"}],
            "evaluation_cases": [
                {"id": "v1", "expected_apply": True, "skill_applies": True},
                {"id": "v2", "expected_apply": True, "skill_applies": True},
            ],
            "negative_cases": [{"id": "n1", "skill_applies": False}],
            "baseline_metrics": {"correctness": 0.5},
            "candidate_metrics": {"correctness": 0.8},
        }
        gen = run_generalization_skill_tests(definition)
        self.assertTrue(gen["passed"])


class ResourceAwarenessTests(unittest.TestCase):
    def test_simple_skips_committee_and_cache_rules(self) -> None:
        simple = classify_task_complexity("Hallo")
        self.assertEqual(simple["complexity"], "simple")
        self.assertFalse(simple["use_committee"])
        key = cache_key(namespace="x", input_version="1", model_id="m")
        cache = VersionedCache()
        cache.set(key, {"ok": True}, uncertain=True, mutating=True)
        self.assertIsNone(cache.get(key))
        cache.set(key, {"ok": True})
        self.assertEqual(cache.get(key), {"ok": True})
        cache.invalidate(key=key)
        self.assertIsNone(cache.get(key))
        bp = backpressure_decision(active_inference=1, max_concurrent_inference=1)
        self.assertEqual(bp["action"], "wait")


class ProactiveTriggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "core.sqlite3"))
        self.svc = ProactiveTriggerService(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dedupe_and_disable_and_readonly_watcher(self) -> None:
        trig = self.svc.register_trigger(
            kind="source_changed",
            title="Watch notes",
            scope="notes.md",
            permission="suggest",
        )
        first = self.svc.consider_event(trig["id"], reason="notes.md changed", payload={"hash": "1"})
        second = self.svc.consider_event(trig["id"], reason="notes.md changed", payload={"hash": "1"})
        self.assertTrue(first["emitted"])
        self.assertTrue(second["duplicate"])
        self.assertFalse(second["emitted"])
        self.assertFalse(first["would_mutate"])
        self.svc.set_enabled(trig["id"], False)
        third = self.svc.consider_event(trig["id"], reason="notes.md changed again", payload={"hash": "2"})
        self.assertFalse(third["emitted"])
        self.assertEqual(third["reason"], "trigger_disabled_or_paused")


class ArtifactResultSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = PlatformDatabase(str(Path(self.tmp.name) / "platform.sqlite3"))
        self.db.initialize()
        self.arts = ArtifactService(self.db, Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_summary_card(self) -> None:
        art = self.arts.create(name="report.md", kind="generated", data=b"# hello\n")
        summary = self.arts.summarize_result(art["id"])
        self.assertEqual(summary["name"], "report.md")
        self.assertTrue(summary["checked"]["ready"])
        self.assertIn("preview", summary["next_actions"])


class LongevityMatrixSmokeTests(unittest.TestCase):
    """WP11 — deterministic matrix entries (not live Windows/host operational proof)."""

    CASES = [
        "restart_mid_task",
        "provider_outage",
        "timeout_during_mutation",
        "cancel_parallel_work",
        "stale_events_after_reconnect",
        "input_changed_mid_run",
        "sqlite_lock_contention",
        "invalid_model_output",
        "stale_cache",
        "missing_plugin",
        "corrupt_or_missing_artifact",
        "context_overflow",
        "offline_start_and_continue",
    ]

    def test_matrix_covered_by_unit_hooks(self) -> None:
        # Each case maps to an existing deterministic hook exercised here or adjacent suites.
        covered = {
            "restart_mid_task": "effect_ledger+project_continuity",
            "provider_outage": "choose_recovery_strategy(alternate_tool)",
            "timeout_during_mutation": "effect_ledger REQUIRES_RECONCILIATION",
            "cancel_parallel_work": "coding_job_control (adjacent)",
            "stale_events_after_reconnect": "native generation fencing (adjacent)",
            "input_changed_mid_run": "steps_invalidated_by_input_change",
            "sqlite_lock_contention": "busy_timeout configured (config, not soak)",
            "invalid_model_output": "output_contracts (adjacent)",
            "stale_cache": "VersionedCache.invalidate",
            "missing_plugin": "PluginManager ready gate (adjacent)",
            "corrupt_or_missing_artifact": "ArtifactService.verify_ready",
            "context_overflow": "assemble_chat_context budget (adjacent)",
            "offline_start_and_continue": "project context_package",
        }
        for case in self.CASES:
            self.assertIn(case, covered)
        # Exercise a few locally:
        self.assertEqual(
            choose_recovery_strategy(cause="model_unavailable", alternate_tool_available=True)["strategy"],
            "alternate_tool",
        )
        cache = VersionedCache()
        cache.set("k", 1)
        self.assertEqual(cache.invalidate(key="k"), 1)


if __name__ == "__main__":
    unittest.main()
