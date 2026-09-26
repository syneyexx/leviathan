"""W180 — memory regression harness writes JSON and enforces non-linear bound."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "benchmark_dataset_memory.py"
REPORT = ROOT / "Data" / "backend" / "tests" / "memory_regression_latest.json"


class MemoryRegressionHarnessTests(unittest.TestCase):
    def test_harness_small_sizes_writes_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lev-w180-") as tmp:
            out = Path(tmp) / "memory_regression_latest.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--sizes",
                    "50,150",
                    "--out",
                    str(out),
                    "--max-bytes-per-row",
                    "65536",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertTrue(out.is_file())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report.get("wave"), "W180")
            self.assertEqual(len(report.get("results") or []), 2)
            bound = report.get("nonLinearWorkingSet") or {}
            self.assertTrue(bound.get("asserted"))
            self.assertTrue(bound.get("passed"), bound)
            self.assertTrue(report.get("truth", {}).get("workingSetMustNotGrowLinearlyWithN"))

            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.assertTrue(REPORT.is_file())

    def test_assert_helper_flags_linear_growth(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "benchmark_dataset_memory", SCRIPT
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fake = [
            {"rows": 100, "peakRssBytes": 10_000_000, "inputBytes": 10_000},
            {"rows": 1000, "peakRssBytes": 10_000_000 + 900 * 100_000, "inputBytes": 100_000},
        ]
        result = mod.assert_non_linear_working_set(fake, max_bytes_per_row=8_192)
        self.assertTrue(result["asserted"])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
