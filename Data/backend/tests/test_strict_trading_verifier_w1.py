"""Wave 1 — strict trading verifier honesty / readiness truth."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]


def _load_verifier():
    path = ROOT / "scripts" / "verify_trading_100.py"
    spec = importlib.util.spec_from_file_location("verify_trading_100_strict", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StrictTradingVerifierTests(unittest.TestCase):
    def test_deferred_pytest_not_strict_pass(self) -> None:
        mod = _load_verifier()
        gate = {
            "title": "t",
            "status": "PASS",
            "required": True,
            "evidence": ["claimed"],
            "checks": [{"kind": "pytest", "node_ids": ["Data/backend/tests/test_verifier_honesty.py"]}],
        }
        row = mod._evaluate_gate("T01", gate, run_tests=False, strict=True)
        self.assertEqual(row["status"], "UNMEASURED")
        self.assertFalse(row["strict_pass"])
        self.assertTrue(any("deferred" in str(e) for e in row["evidence"]))

    def test_file_exists_only_not_pass(self) -> None:
        mod = _load_verifier()
        gate = {
            "title": "t",
            "status": "PASS",
            "required": True,
            "evidence": ["claimed"],
            "checks": [{"kind": "file_exists", "path": "scripts/verify_trading_100.py"}],
        }
        row = mod._evaluate_gate("T02", gate, run_tests=True, strict=True)
        self.assertEqual(row["status"], "UNMEASURED")
        self.assertFalse(row["strict_pass"])

    def test_required_feature_gated_blocks_strict_all_pass(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_trading_100.py"),
                "--strict",
                "--no-anti-shortcut",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        report = json.loads(
            (ROOT / "Data" / "backend" / "tests" / "trading_completion_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(report["strict"])
        self.assertFalse(report["strict_all_required_pass"])
        self.assertFalse(report["all_required_pass"])
        self.assertIsNotNone(report.get("source_commit"))
        self.assertTrue(report["truth"]["deferred_pytest_is_not_strict_pass"])
        self.assertTrue(report["truth"]["feature_gated_is_not_pass_claim"])
        statuses = {row["status"] for row in report["gates"]}
        # G16 remains FEATURE_GATED but is outside the supported operating envelope
        # (required=false). Strict still fails without --run-tests (deferred pytest).
        self.assertIn("FEATURE_GATED", statuses)
        # Without --run-tests, claimed PASS gates with pytest checks become UNMEASURED.
        self.assertIn("UNMEASURED", statuses)

    def test_stale_expect_commit_not_release_evidence(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_trading_100.py"),
                "--allow-incomplete",
                "--expect-commit",
                "0" * 40,
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        report = json.loads(
            (ROOT / "Data" / "backend" / "tests" / "trading_completion_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(report["stale_source_commit"])
        self.assertFalse(report["all_required_pass"])

    def test_strict_rejects_allow_incomplete(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_trading_100.py"),
                "--strict",
                "--allow-incomplete",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_hades_editor_not_in_trading_owned_globs(self) -> None:
        mod = _load_verifier()
        joined = " ".join(mod.TRADING_OWNED_GLOBS)
        self.assertNotIn("HADES", joined)
        self.assertNotIn("editor/", joined)

    def test_institutional_program_not_pass_authority(self) -> None:
        path = ROOT / "Data" / "backend" / "tests" / "institutional_trading_program.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(data.get("pass_authority"))
        self.assertEqual(data.get("authority"), "HISTORICAL_PROGRAM_DESCRIPTOR")
        self.assertNotIn("baseline_commit", data)  # renamed to historical
        self.assertIn("baseline_commit_historical", data)

    def test_gap_ledger_historical_vs_current(self) -> None:
        from Data.modules.market_sim.institutional_core.gap_ledger import (
            build_capability_gap_matrix,
            build_current_capability_gap_matrix,
        )

        hist = build_capability_gap_matrix()
        cur = build_current_capability_gap_matrix()
        self.assertEqual(hist.generated_from, "historical_baseline_snapshot")
        self.assertIn("current_runtime", cur.generated_from)
        self.assertGreater(len(cur.rows), 0)


if __name__ == "__main__":
    unittest.main()
