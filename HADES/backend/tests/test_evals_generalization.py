"""Generalization eval dataset, holdout judges, harness, and fixture-knowledge absence."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_agent import ExploreHit, _heuristic_fix_from_failing_assert, _heuristic_initial_edits
from evals.generalization_dataset import (
    DEVELOPMENT_EXAMPLES,
    GENERALIZATION_DATASET_VERSION,
    GENERALIZATION_TASKS,
    categories_covered,
    dataset_task_fingerprint,
    list_holdout_tasks,
)
from evals.harness import git_start_commit, run_harness
from evals.holdout_judges import (
    HOLDOUT_JUDGE_VERSION,
    assert_oracle_not_in_agent_paths,
    judge_baseline_must_fail,
    judge_final_from_execution,
    run_holdout_honesty_suite,
)
from evals.independent_tasks import FIXTURE_KIND, INDEPENDENT_TASKS, QUALITY_PROOF


class KnownFixtureLabelTests(unittest.TestCase):
    def test_e01_e08_marked_not_quality_proof(self) -> None:
        self.assertFalse(QUALITY_PROOF)
        self.assertEqual(FIXTURE_KIND, "known_regression_fixtures")
        self.assertEqual(len(INDEPENDENT_TASKS), 8)
        for task in INDEPENDENT_TASKS:
            self.assertFalse(task.get("quality_proof"))
            self.assertEqual(task.get("kind"), FIXTURE_KIND)
            self.assertIn("not independent quality proof", (task.get("note") or "").lower())


class GeneralizationDatasetTests(unittest.TestCase):
    def test_at_least_20_holdout_tasks_with_categories(self) -> None:
        holdout = list_holdout_tasks()
        self.assertGreaterEqual(len(holdout), 20)
        self.assertGreaterEqual(len(GENERALIZATION_TASKS), 20)
        cats = categories_covered()
        for required in (
            "python",
            "ts_js",
            "api_contracts",
            "config",
            "async_concurrency",
            "error_handling",
            "multi_file",
            "docs",
            "user_flow",
        ):
            self.assertGreaterEqual(cats.get(required, 0), 1, cats)
        # Development examples must not pollute holdout.
        self.assertTrue(all(t.get("split") == "holdout" for t in holdout))
        self.assertTrue(all(e.get("split") == "development" for e in DEVELOPMENT_EXAMPLES))
        self.assertEqual(GENERALIZATION_DATASET_VERSION, "generalization_v1")

    def test_fingerprint_stable(self) -> None:
        a = dataset_task_fingerprint()
        b = dataset_task_fingerprint()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_holdout_honesty_all_red(self) -> None:
        report = run_holdout_honesty_suite()
        self.assertTrue(report["all_fixtures_honest"], report["scores"])
        self.assertEqual(report["judge_version"], HOLDOUT_JUDGE_VERSION)
        self.assertGreaterEqual(report["total"], 20)

    def test_js_multiply_is_runtime_not_string_only(self) -> None:
        task = next(t for t in GENERALIZATION_TASKS if t["id"] == "G05_js_multiply")
        root = task["fixture"](variant="test")
        # Baseline must fail via Node execution path.
        row = judge_baseline_must_fail(task, variant="test")
        self.assertTrue(row["honest"])
        check = (root / "run_check.mjs").read_text(encoding="utf-8")
        self.assertIn("multiply(6, 7)", check)
        self.assertNotIn("return a + b", check)  # judge is behavioral, not string oracle on source

    def test_holdout_judge_rejects_claimed_without_tests(self) -> None:
        task = next(t for t in GENERALIZATION_TASKS if t["id"] == "G01_py_sort")
        root = task["fixture"](variant="judge")
        # Unfixed workspace + agent claims verified → claimed_without_evidence.
        judged = judge_final_from_execution(
            task, root, baseline_failed=True, agent_status="verified"
        )
        self.assertFalse(judged["passed"])
        self.assertTrue(judged["claimed_without_evidence"])


class HarnessTests(unittest.TestCase):
    def test_harness_records_metadata_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            report = run_harness(
                dataset="generalization_v1",
                seed=42,
                mode="honesty",
                limit=3,
                out_path=str(out),
            )
            self.assertEqual(report["seed"], 42)
            self.assertEqual(report["dataset"], GENERALIZATION_DATASET_VERSION)
            self.assertTrue(report["task_fingerprint_sha256"])
            self.assertIn("start_commit", report)
            self.assertIn("model_config", report)
            self.assertFalse(report["claimed_agent_quality_pass"])
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["seed"], 42)
            self.assertIn("python -m evals.harness", report["host_command"])

    def test_harness_independent_fixtures_labeled(self) -> None:
        report = run_harness(dataset="independent_fixtures_v1", seed=7, mode="honesty", limit=2)
        self.assertIn("known regression", (report.get("note") or "").lower())
        self.assertFalse(report["claimed_agent_quality_pass"])

    def test_git_start_commit_nonempty(self) -> None:
        sha = git_start_commit()
        self.assertTrue(sha)
        self.assertNotEqual(sha, "")


class FixtureKnowledgeAbsentFromHeuristicsTests(unittest.TestCase):
    def test_agent_source_has_no_holdout_oracles(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "coding_agent.py").read_text(encoding="utf-8")
        violations = assert_oracle_not_in_agent_paths(src)
        self.assertEqual(violations, [])
        self.assertNotIn("G01_py_sort", src)
        self.assertNotIn("generalization_v1", src)
        self.assertNotIn("E01: dumps", src)

    def test_heuristics_do_not_rewrite_generalization_fixtures_without_evidence(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "ranking.py").write_text(
            "def by_score(rows):\n    return sorted(rows, key=lambda r: r['score'])\n",
            encoding="utf-8",
        )
        (root / "math_util.mjs").write_text(
            "export function multiply(a, b) { return a + b; }\n",
            encoding="utf-8",
        )
        (root / "form_flow.py").write_text(
            "def prepare_submit(form, session):\n    return {'name': form.get('name'), 'csrf_token': None}\n",
            encoding="utf-8",
        )
        edits = _heuristic_initial_edits(
            root,
            "fix the bugs in ranking, multiply, and csrf flow",
            [
                ExploreHit(path="ranking.py", reason="explore", score=1.0),
                ExploreHit(path="math_util.mjs", reason="explore", score=1.0),
                ExploreHit(path="form_flow.py", reason="explore", score=1.0),
            ],
        )
        self.assertEqual(edits, [])
        # Failing assert without path implication must not spray fixture knowledge.
        fail_edits = _heuristic_fix_from_failing_assert(
            root,
            "FAIL: something\nAssertionError: lists differ",
        )
        self.assertEqual(fail_edits, [])


if __name__ == "__main__":
    unittest.main()
