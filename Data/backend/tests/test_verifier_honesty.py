"""W0C — verifier honesty: incomplete ≠ PASS; runner does not crash."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class VerifierHonestyTests(unittest.TestCase):
    def test_aggregate_runner_allow_incomplete_exits_zero(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_leviathan.py"),
                "--allow-incomplete",
                "--write-report",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report_path = ROOT / "Data" / "backend" / "tests" / "leviathan_verification_report.json"
        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["truth"]["incomplete_is_not_pass"])
        self.assertTrue(report["truth"]["baseline_green_does_not_mark_frontier_pass"])
        self.assertTrue(report["allow_incomplete"])
        self.assertEqual(report["exit_code"], 0)

    def test_frontier_without_allow_exits_nonzero_when_gates_open(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_frontier_reasoning.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        # R01-R30 are NOT_STARTED on current main — must not silently PASS.
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("not all PASS", proc.stdout + proc.stderr)

    def test_trading_allow_incomplete_does_not_claim_all_pass(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_trading_100.py"),
                "--allow-incomplete",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(
            (ROOT / "Data" / "backend" / "tests" / "trading_completion_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(report.get("all_required_pass"))
        self.assertTrue(report["truth"]["incomplete_is_not_pass"])
        self.assertTrue(report["allow_incomplete"])
        # At least one required gate must still be incomplete on current main.
        statuses = {row["status"] for row in report["gates"]}
        self.assertTrue(statuses & {"NOT_STARTED", "IN_PROGRESS", "UNMEASURED", "FEATURE_GATED"})

    def test_missing_gates_manifest_does_not_traceback(self) -> None:
        import importlib.util

        path = ROOT / "scripts" / "verify_trading_100.py"
        spec = importlib.util.spec_from_file_location("verify_trading_100_probe", path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        original = mod.GATES_PATH
        try:
            mod.GATES_PATH = Path(tempfile.mkdtemp()) / "missing_gates.json"
            code = mod.main([])
            self.assertEqual(code, 2)
        finally:
            mod.GATES_PATH = original


if __name__ == "__main__":
    unittest.main()
