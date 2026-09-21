"""A13 — reliable resume experiment harness tests (software layer)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.resume_experiment import TASKS, run_experiment


class A13ResumeExperimentTests(unittest.TestCase):
    def test_experiment_produces_raw_and_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            import evals.resume_experiment as mod

            old_default = mod.default_out_dir
            old_evidence = mod.evidence_out_dir
            mod.default_out_dir = lambda: Path(tmp) / "artifacts"
            mod.evidence_out_dir = lambda: Path(tmp) / "evidence"
            try:
                report = run_experiment(runs=2, seed=7, out_path=out)
                self.assertTrue(report["ok"])
                self.assertTrue(out.is_file())
                self.assertEqual(report["settings"]["quality_layer"], "software")
                self.assertFalse(report["settings"]["exactly_once_claimed"])
                self.assertTrue(report["honesty"]["exactly_once_not_claimed"])
                raw = report["raw_results"]
                self.assertEqual(len(raw), 2 * len(TASKS) * 2)
                self.assertIn("recovery_on", report["aggregate"])
                self.assertIn("recovery_off", report["aggregate"])
                self.assertIn("benefit", report["aggregate"])
                self.assertTrue(report["aggregate"]["analysis"])
                self.assertTrue(report["aggregate"]["limits"])
                off = report["aggregate"]["recovery_off"]
                on = report["aggregate"]["recovery_on"]
                self.assertGreaterEqual(
                    off["lost_work_rate"] + off["false_success_rate"] + off["duplicate_effects_rate"],
                    0.0,
                )
                self.assertGreater(on["n"], 0)
                self.assertGreater(off["n"], 0)
                reloaded = json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(len(reloaded["raw_results"]), len(raw))
            finally:
                mod.default_out_dir = old_default
                mod.evidence_out_dir = old_evidence
    def test_no_universal_exactly_once_in_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import evals.resume_experiment as mod

            mod.default_out_dir = lambda: Path(tmp) / "artifacts"
            mod.evidence_out_dir = lambda: Path(tmp) / "evidence"
            report = run_experiment(runs=1, seed=1, out_path=Path(tmp) / "r.json")
        self.assertFalse(report["settings"]["exactly_once_claimed"])
        joined = " ".join(report["aggregate"]["limits"]).lower()
        self.assertIn("exactly-once", joined)


if __name__ == "__main__":
    unittest.main()
