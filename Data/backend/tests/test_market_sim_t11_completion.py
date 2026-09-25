"""T11 — Master Program closeout: verifier, completion report, Windows paths, migrations."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from Data.backend.migrations import MIGRATIONS
from Data.modules.market_sim.paths import (
    job_sandbox_dir,
    normalize_market_path,
    windows_style_to_posix,
)

ROOT = Path(__file__).resolve().parents[3]
GATES = ROOT / "Data" / "backend" / "tests" / "trading_gates.json"
REPORT = ROOT / "Data" / "backend" / "tests" / "trading_completion_report.json"
VERIFY = ROOT / "scripts" / "verify_trading_100.py"
CI = ROOT / ".github" / "workflows" / "leviathan-ci.yml"
COMPLETION_MD = ROOT / "Data" / "docs" / "trading_master_program_completion.md"
GOLDEN = ROOT / "Data" / "backend" / "tests" / "fixtures" / "market_sim_golden_fills.json"
CHAR = ROOT / "Data" / "backend" / "tests" / "test_market_sim_characterization.py"


class VerifyTrading100Tests(unittest.TestCase):
    def test_verifier_script_exists_and_mentions_gates(self) -> None:
        self.assertTrue(VERIFY.is_file())
        text = VERIFY.read_text(encoding="utf-8")
        self.assertIn("trading_gates.json", text)
        self.assertIn("DEFERRED", text)
        self.assertIn("anti-shortcut", text.replace("_", "-") or text)

    def test_ci_invokes_trading_verifier(self) -> None:
        text = CI.read_text(encoding="utf-8")
        self.assertIn("verify_trading_100.py", text)

    def test_system_doc_points_at_verifier(self) -> None:
        doc = (ROOT / "Data" / "docs" / "Leviathan_system_backend.md").read_text(encoding="utf-8")
        self.assertIn("verify_trading_100.py", doc)
        self.assertIn("T11", doc)


class CompletionReportTests(unittest.TestCase):
    def test_completion_markdown_exists(self) -> None:
        self.assertTrue(COMPLETION_MD.is_file())
        text = COMPLETION_MD.read_text(encoding="utf-8")
        self.assertIn("Master Program v4", text)
        self.assertIn("Evidence", text)
        self.assertIn("DEFERRED", text)

    def test_gates_phase_is_t11(self) -> None:
        manifest = json.loads(GATES.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("phase"), "T11")
        for gid in ("G43", "G44", "G45", "G47", "G60"):
            self.assertEqual(manifest["gates"][gid]["status"], "PASS", gid)


class CharacterizationRegressionTests(unittest.TestCase):
    def test_golden_fills_fixture_present(self) -> None:
        self.assertTrue(GOLDEN.is_file())
        data = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data.get("fills") or []), 1)

    def test_d28_desired_no_longer_expected_failure(self) -> None:
        text = CHAR.read_text(encoding="utf-8")
        # Desired golden-fill contract is now a real regression (fixture present).
        self.assertIn("market_sim_golden_fills.json", text)
        self.assertNotIn(
            "@unittest.expectedFailure  # D28",
            text,
        )


class WindowsPathTests(unittest.TestCase):
    def test_normalize_windows_style_under_root(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = normalize_market_path(r"C:\data\BTCUSDT_1h.csv", root=root)
            self.assertEqual(out, (root / "data" / "BTCUSDT_1h.csv").resolve())
            self.assertEqual(windows_style_to_posix(r"C:\foo\bar.csv"), "C:/foo/bar.csv")
            sandbox = job_sandbox_dir(root, "job:abc/../../escape")
            self.assertTrue(sandbox.name.startswith("job_abc"))
            self.assertTrue(str(sandbox).startswith(str(root.resolve())))

    def test_refuse_escape(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                normalize_market_path("../outside.csv", root=root)


class MigrationPostureTests(unittest.TestCase):
    def test_migration_head_documented(self) -> None:
        self.assertGreaterEqual(MIGRATIONS[-1].version, 49)
        # Compatibility posture: migrations are append-only numbered sequence.
        versions = [m.version for m in MIGRATIONS]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(len(versions), len(set(versions)))


if __name__ == "__main__":
    unittest.main()
