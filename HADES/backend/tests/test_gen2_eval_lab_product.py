"""Product-depth tests for Gen2 Intelligence Evaluation Lab (D1–D13)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.gen2_release_gate import EMBEDDED_BASELINE, run_gate
from gen2.eval_lab import (
    detect_flaky_cases,
    expand_software_metrics,
    ingest_flight_recorder_run,
    list_eval_catalog,
    pr_help_summary,
    run_ab_experiment,
    run_eval_lab,
    run_red_team_suite,
)
from gen2.flight_recorder import record
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class EvalLabProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "eval.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_catalog_wraps_suites(self) -> None:
        catalog = list_eval_catalog()
        self.assertTrue(catalog.get("offline"))
        ids = {s["id"] for s in catalog["suites"]}
        self.assertIn("reasoning", ids)
        self.assertIn("red_team_v1", ids)
        self.assertIn("generalization_v1", ids)
        self.assertTrue(any(s["id"].startswith("quality") for s in catalog["suites"]))

    def test_red_team_software_defenses(self) -> None:
        report = run_red_team_suite()
        self.assertEqual(report["suite"], "red_team_v1")
        self.assertEqual(report["pass_rate"], 1.0)
        self.assertTrue(report["not_model_quality"])
        self.assertFalse(report["model_invoked"])
        for score in report["scores"]:
            metrics = score["metrics"]
            for key in (
                "hallucination_proxy",
                "citation_coverage",
                "tool_accuracy",
                "replan_count",
                "retries",
            ):
                self.assertIn(key, metrics)

    def test_metrics_expansion_on_reasoning(self) -> None:
        report = run_eval_lab(self.store, model_id="m", suite="reasoning")
        self.assertTrue(report["summary"]["not_model_quality"])
        sample = report["scores"][0]
        metrics = expand_software_metrics(sample)
        self.assertIn("hallucination_proxy", metrics)
        self.assertIn("tool_accuracy", metrics)

    def test_holdout_generalization_wire(self) -> None:
        report = run_eval_lab(
            self.store,
            model_id="holdout",
            suite="generalization_v1",
            mode="holdout_honesty",
            holdout_limit=2,
        )
        self.assertEqual(report["suite"], "generalization_v1")
        self.assertEqual(report["mode"], "holdout_honesty")
        self.assertTrue(report["summary"]["not_model_quality"])
        self.assertGreaterEqual(report["summary"]["total"], 1)

    def test_ab_n_too_small_honesty(self) -> None:
        ab = run_ab_experiment(
            self.store,
            strategy_a="base",
            strategy_b="alt",
            suite="reasoning",
            n=2,
        )
        summary = ab["summary"]
        self.assertEqual(summary["ci_status"], "n_too_small")
        self.assertIsNone(summary["a"]["ci95"])
        self.assertEqual(summary["mode"], "ab_experiment")

    def test_flaky_detection_oscillation(self) -> None:
        # Fabricate oscillating scores via saved runs.
        for i, passed in enumerate([True, False, True]):
            self.store.save_eval_run(
                suite="reasoning",
                mode="deterministic_software",
                model_id=f"software:t{i}",
                summary={"pass_rate": 1.0 if passed else 0.0, "total": 1, "passed": int(passed), "failed": int(not passed)},
                scores=[
                    {
                        "scenario_id": "S_FLAKY",
                        "passed": passed,
                        "task_type": "reasoning",
                        "metrics": {"pass": 1.0 if passed else 0.0},
                    }
                ],
            )
        flaky = detect_flaky_cases(self.store, suite="reasoning", mode="deterministic_software", last_n=5)
        self.assertGreaterEqual(flaky["flaky_count"], 1)
        self.assertTrue(any(c["scenario_id"] == "S_FLAKY" for c in flaky["flaky_cases"]))

    def test_pr_help_delta_and_regressions(self) -> None:
        a = self.store.save_eval_run(
            suite="reasoning",
            mode="deterministic_software",
            model_id="software:a",
            summary={"pass_rate": 1.0, "total": 2, "passed": 2, "failed": 0},
            scores=[
                {"scenario_id": "S1", "passed": True, "metrics": {"pass": 1.0}},
                {"scenario_id": "S2", "passed": True, "metrics": {"pass": 1.0}},
            ],
        )
        b = self.store.save_eval_run(
            suite="reasoning",
            mode="deterministic_software",
            model_id="software:b",
            summary={"pass_rate": 0.5, "total": 2, "passed": 1, "failed": 1},
            scores=[
                {"scenario_id": "S1", "passed": True, "metrics": {"pass": 1.0}},
                {"scenario_id": "S2", "passed": False, "metrics": {"pass": 0.0}},
            ],
        )
        help_ = pr_help_summary(self.store, a["id"], b["id"])
        self.assertTrue(help_["ok"])
        self.assertEqual(help_["delta_pass_rate"], -0.5)
        self.assertIn("S2", help_["regressions"])
        self.assertFalse(help_["helped"])

    def test_historical_flight_ingest(self) -> None:
        record(self.store, "hist1", "RUN_CREATED", {})
        record(self.store, "hist1", "VERIFY", {"passed": True})
        record(self.store, "hist1", "TOOL", {"ok": True, "tool_name": "read"})
        record(self.store, "hist1", "TERMINAL", {"status": "completed", "ok": True})
        ingested = ingest_flight_recorder_run(self.store, "hist1")
        self.assertEqual(ingested["mode"], "historical_flight_ingest")
        self.assertTrue(ingested["summary"]["not_model_quality"])
        self.assertGreaterEqual(ingested["summary"]["total"], 1)

    def test_services_facade_and_release_gate(self) -> None:
        cat = self.svc.eval_catalog()
        self.assertGreaterEqual(cat["suite_count"], 3)
        report = run_gate(db_path=str(Path(self.temp.name) / "gate.db"))
        self.assertTrue(report["ok"], msg=report.get("regressions"))
        self.assertTrue(report["offline"])
        self.assertIn("reasoning", EMBEDDED_BASELINE["suites"])


if __name__ == "__main__":
    unittest.main()
