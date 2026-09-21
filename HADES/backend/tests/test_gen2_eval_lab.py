"""Characterization tests for Gen2 Eval Lab extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.eval_lab import (
    capability_matrix,
    eval_reports,
    recommend_model,
    run_eval_lab,
    task_type_for_scenario,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class EvalLabModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "eval.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_task_type_for_scenario_keywords(self) -> None:
        self.assertEqual(task_type_for_scenario("tool_use", "call tools"), "tools")
        self.assertEqual(task_type_for_scenario("verify_evidence", "fake claim"), "verification")
        self.assertEqual(task_type_for_scenario("work_runtime_complex", "plan"), "planning")
        self.assertEqual(task_type_for_scenario("ctx", "role packing"), "context")
        self.assertEqual(task_type_for_scenario("offline_net", "network"), "routing")
        self.assertEqual(task_type_for_scenario("fast_path", "fast reply"), "chat")
        self.assertEqual(task_type_for_scenario("logic", "deduce"), "reasoning")

    def test_run_eval_lab_deterministic_honesty(self) -> None:
        report = run_eval_lab(self.store, model_id="unit-model")
        self.assertEqual(report["status"], "completed")
        summary = report["summary"]
        self.assertTrue(summary["not_model_quality"])
        self.assertFalse(summary["model_invoked"])
        self.assertEqual(summary["quality_layer"], "software")
        self.assertEqual(summary["matrix_model_id"], "software:unit-model")
        self.assertGreaterEqual(summary["total"], 10)
        for score in report["scores"]:
            self.assertFalse(score["model_invoked"])
            self.assertEqual(score["quality_layer"], "software")
            self.assertIn("task_type", score)

    def test_capability_matrix_and_recommend(self) -> None:
        run_eval_lab(self.store, model_id="unit-model")
        matrix = capability_matrix(self.store)
        self.assertGreater(len(matrix["rows"]), 0)
        self.assertTrue(matrix["by_model"])
        rec = recommend_model(self.store, "verification")
        self.assertIn(rec.get("source"), {"empirical_matrix", "software_suite_fallback"})
        if rec.get("source") == "software_suite_fallback":
            self.assertIn("not live model quality", rec.get("note", "").lower())

    def test_recommend_without_data(self) -> None:
        out = recommend_model(self.store, "coding")
        self.assertIsNone(out["model_id"])
        self.assertEqual(out["source"], "no_empirical_data")
        self.assertIn("no hardcoded", out["note"].lower())

    def test_eval_reports_lists_runs(self) -> None:
        run_eval_lab(self.store, model_id="a")
        runs = eval_reports(self.store, limit=10)
        self.assertGreaterEqual(len(runs), 1)

    def test_services_delegate_facade(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        self.assertEqual(svc._task_type_for_scenario("tool_x", "tools"), "tools")
        report = svc.run_eval_lab(model_id="facade-model")
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["summary"]["not_model_quality"])
        matrix = svc.capability_matrix()
        self.assertGreater(len(matrix["rows"]), 0)
        rec = svc.recommend_model("verification")
        self.assertIn(rec.get("source"), {"empirical_matrix", "software_suite_fallback"})
        self.assertGreaterEqual(len(svc.eval_reports(limit=5)), 1)


if __name__ == "__main__":
    unittest.main()
