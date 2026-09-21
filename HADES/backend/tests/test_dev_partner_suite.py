"""Development Partner suite, harness, delivery, autonomy, and human rating contracts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_autonomy import normalize_coding_autonomy, profile_policy, recommend_profile
from coding_delivery import build_coding_delivery, validate_delivery_for_completion
from evals.dev_partner_harness import run_dev_partner_suite, run_single_task
from evals.dev_partner_improve import assert_improvement_cannot_rewrite_judges, propose_improvement_from_failures
from evals.dev_partner_judges import (
    assert_grader_outside_workspace,
    baseline_must_be_red_or_report,
    judge_dev_partner_task,
)
from evals.dev_partner_suite import (
    DEV_PARTNER_DATASET_VERSION,
    DEV_PARTNER_TASKS,
    list_development_tasks,
    list_holdout_tasks,
    suite_manifest,
    task_type_counts,
)
from evals.failure_taxonomy import classify_failure


class DevPartnerSuiteContractTests(unittest.TestCase):
    def test_twenty_tasks_and_distribution(self) -> None:
        self.assertEqual(len(DEV_PARTNER_TASKS), 20)
        counts = task_type_counts()
        self.assertEqual(counts.get("bugfix"), 8)
        self.assertEqual(counts.get("feature"), 4)
        self.assertEqual(counts.get("regression"), 4)
        self.assertEqual(counts.get("review"), 4)
        self.assertEqual(DEV_PARTNER_DATASET_VERSION, "dev_partner_v1")
        manifest = suite_manifest()
        self.assertEqual(manifest["development_count"], 12)
        self.assertEqual(manifest["holdout_count"], 8)
        self.assertTrue(manifest["task_fingerprint_sha256"])

    def test_split_freeze(self) -> None:
        dev_ids = {t["short_id"] for t in list_development_tasks()}
        hold_ids = {t["short_id"] for t in list_holdout_tasks()}
        self.assertTrue(dev_ids.isdisjoint(hold_ids))
        self.assertEqual(len(dev_ids) + len(hold_ids), 20)


class HonestyAndJudgeTests(unittest.TestCase):
    def test_bugfix_baseline_is_red(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP01")
        root = task["fixture"](variant="development")
        base = baseline_must_be_red_or_report(task, root)
        self.assertTrue(base["honest"])
        self.assertFalse(base["passed"])

    def test_wrong_patch_rejected(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP01")
        root = task["fixture"](variant="development")
        # Incorrect "fix" that keeps ascending sort
        (root / "ranking.py").write_text(
            "def by_score(rows):\n    return sorted(rows, key=lambda r: r['score'])\n",
            encoding="utf-8",
        )
        judged = judge_dev_partner_task(task, root, baseline_failed=True, agent_claimed_success=True)
        self.assertFalse(judged["passed"])
        self.assertTrue(judged.get("false_success"))

    def test_correct_bugfix_passes(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP01")
        root = task["fixture"](variant="development")
        (root / "ranking.py").write_text(
            "def by_score(rows):\n    return sorted(rows, key=lambda r: r['score'], reverse=True)\n",
            encoding="utf-8",
        )
        judged = judge_dev_partner_task(task, root, baseline_failed=True)
        self.assertTrue(judged["passed"])

    def test_missing_required_output_not_completed(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP10")
        root = task["fixture"](variant="development")
        judged = judge_dev_partner_task(task, root, agent_claimed_success=True)
        self.assertFalse(judged["passed"])
        self.assertEqual(judged.get("reason"), "missing_review_report")

    def test_ungrounded_review_does_not_auto_pass(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP10")
        root = task["fixture"](variant="development")
        art = root / "artifacts"
        art.mkdir(exist_ok=True)
        (art / "review_report.json").write_text(
            json.dumps(
                {
                    "findings": [
                        {"severity": "nit: prefer prettier formatting", "evidence": "", "severity": "low"}
                    ],
                    "fabricated_issues": False,
                }
            ),
            encoding="utf-8",
        )
        judged = judge_dev_partner_task(task, root)
        self.assertFalse(judged["passed"])

    def test_grader_not_in_workspace(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP01")
        root = task["fixture"](variant="development")
        self.assertEqual(assert_grader_outside_workspace(root), [])
        # Injecting a grader copy is detected
        (root / "dev_partner_judges.py").write_text("# injected\n", encoding="utf-8")
        self.assertTrue(assert_grader_outside_workspace(root))


class DeliveryAndAutonomyTests(unittest.TestCase):
    def test_incomplete_delivery_cannot_complete(self) -> None:
        delivery = build_coding_delivery(
            goal="fix sort",
            task_type="bugfix",
            understanding="fix sort",
            changed_files=[],
            diff_text="",
            checks_run=[],
            test_results=[],
            uncertainties=["none"],
            status="completed",
        )
        self.assertFalse(delivery["complete"])
        self.assertEqual(delivery["status"], "incomplete")
        gate = validate_delivery_for_completion(delivery)
        self.assertFalse(gate["allowed"])

    def test_analyze_only_blocks_edits(self) -> None:
        policy = profile_policy("analyze_only")
        self.assertFalse(policy["allow_workspace_edits"])
        self.assertFalse(policy["allow_apply_to_source"])
        self.assertFalse(policy["allow_external_publish"])
        self.assertEqual(normalize_coding_autonomy("read_only"), "analyze_only")

    def test_recommendation_does_not_auto_grant(self) -> None:
        rec = recommend_profile(
            task_kind="simple_local_bugfix",
            measured_pass_rate=0.95,
            human_usable_rate=0.9,
        )
        self.assertEqual(rec["activation"], "explicit_user_opt_in")
        self.assertTrue(rec["revocable"])


class HarnessSoftwareTests(unittest.TestCase):
    def test_honesty_suite(self) -> None:
        report = run_dev_partner_suite(mode="honesty", split="holdout", limit=8)
        self.assertEqual(report["dataset"], DEV_PARTNER_DATASET_VERSION)
        self.assertTrue(report["passed"] >= 8)
        self.assertFalse(report["claimed_agent_quality_pass"])

    def test_baseline_compare_shows_improvement(self) -> None:
        report = run_dev_partner_suite(mode="baseline_compare", split="development", limit=8)
        self.assertIn("baseline", report)
        self.assertIn("improved", report)
        self.assertGreaterEqual(report["improved"]["pass_rate"], report["baseline"]["pass_rate"])
        self.assertEqual(report["live_agent_quality"], "UNMEASURED")

    def test_provider_unavailable_not_pass(self) -> None:
        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP01")
        # Force executable without LM by not mocking — expect UNMEASURED or measured via heuristics only.
        # Use classify_failure directly for the contract.
        failure = classify_failure(route_out={"status": "unmeasured", "provider_unavailable": True})
        self.assertEqual(failure["failure_class"], "PROVIDER_UNAVAILABLE")


class ImproveLoopGuardsTests(unittest.TestCase):
    def test_cannot_rewrite_judges_via_workspace(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="dp_improve_"))
        check = assert_improvement_cannot_rewrite_judges(root)
        self.assertTrue(check["ok"])
        (root / "holdout_judges.py").write_text("pass\n", encoding="utf-8")
        check2 = assert_improvement_cannot_rewrite_judges(root)
        self.assertFalse(check2["ok"])

    def test_proposal_keeps_guards(self) -> None:
        # Use a tiny compare report stub to avoid long runtime in this unit.
        stub = {
            "baseline": {"pass_rate": 0.1, "failures": {"top_bottleneck": "MISSING_REQUIRED_OUTPUT", "recurring": []}},
            "improved": {"pass_rate": 0.8, "failures": {}},
            "delta_pass_rate": 0.7,
            "live_agent_quality": "UNMEASURED",
        }
        proposal = propose_improvement_from_failures(failure_report=stub, split="development")
        self.assertFalse(proposal["guards"]["may_modify_independent_judges"])
        self.assertFalse(proposal["guards"]["may_auto_merge_main"])
        self.assertTrue(proposal["recommend_apply"])
        self.assertEqual(proposal["activation"], "explicit_human_review")


class HumanRatingStoreTests(unittest.TestCase):
    def test_human_rating_preserves_original(self) -> None:
        from gen2.store import Gen2Store

        db_path = Path(tempfile.mkdtemp()) / "gen2.db"
        store = Gen2Store(str(db_path))
        original = {"passed": False, "status": "incomplete"}
        row = store.save_human_usability_rating(
            rating="usable_after_small_correction",
            eval_run_id="eval_test",
            task_id="DP01_bugfix",
            correction_notes="Renamed one symbol",
            correction_seconds=120,
            timer_opt_in=True,
            original_result=original,
            primary_error="INCORRECT_CHANGE",
        )
        self.assertEqual(row["rating"], "usable_after_small_correction")
        self.assertEqual(row["original_result"], original)
        trends = store.human_usability_trends()
        self.assertEqual(trends["measured_correction_samples"], 1)
        self.assertIsNotNone(trends["mean_correction_seconds"])


class CodingAgentReportPathTests(unittest.TestCase):
    def test_review_task_produces_report_without_forced_patch(self) -> None:
        from build_agent import BuildAgentService
        from coding_agent import CodingAgentService

        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP10")
        root = task["fixture"](variant="development")
        build = BuildAgentService(root.parent)
        coding = CodingAgentService(build)
        result = coding.run_from_goal(
            root,
            task["goal"],
            task_type="review",
            autonomy_profile="reviewable_result",
            auto_repair=False,
        )
        report = Path(result["work_root"]) / "artifacts" / "review_report.json"
        self.assertTrue(report.is_file(), result.get("coding"))
        self.assertFalse(result.get("applied_edits"))
        delivery = (result.get("coding") or {}).get("delivery") or {}
        self.assertEqual(delivery.get("schema"), "coding_delivery_v1")

    def test_user_source_not_mutated_on_report_path(self) -> None:
        from build_agent import BuildAgentService
        from coding_agent import CodingAgentService

        task = next(t for t in DEV_PARTNER_TASKS if t["short_id"] == "DP08")
        root = task["fixture"](variant="development")
        before = (root / "label.py").read_text(encoding="utf-8")
        build = BuildAgentService(root.parent)
        coding = CodingAgentService(build)
        coding.run_from_goal(root, task["goal"], task_type="regression", auto_repair=False)
        after = (root / "label.py").read_text(encoding="utf-8")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
