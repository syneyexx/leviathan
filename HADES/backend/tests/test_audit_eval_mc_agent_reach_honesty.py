"""Mission Control empty-result toasts + agent-reach install empty honesty."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


class EvalMcAgentReachHonestyTests(unittest.TestCase):
    def test_mission_control_empty_result_toasts(self) -> None:
        page = (ROOT / "components" / "hades" / "pages" / "mission-control-page.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('toast.message("Matrix leeg (0 rijen)")', page)
        self.assertIn("Flaky-detectie: geen eval-runs om te beoordelen", page)
        self.assertIn('toast.message("0 reports")', page)
        self.assertIn("Context-pack leeg (kept=0", page)
        self.assertIn('toast.message("0 compute nodes")', page)
        self.assertIn('toast.message("0 sandbox profiles")', page)
        self.assertIn('toast.message("0 contradictions")', page)
        self.assertIn('toast.message("0 analogues gevonden")', page)
        self.assertNotIn('toast.success(`Matrix: ${matrix.rows?.length ?? 0} rijen`)', page)
        self.assertNotIn('toast.success("Flaky-detectie voltooid")', page)
        self.assertNotIn('toast.success("Analogues zoekresultaat")', page)

    def test_detect_flaky_empty_runs_not_ok(self) -> None:
        from gen2.eval_lab import detect_flaky_cases
        from gen2.store import Gen2Store

        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "gen2.db"))
            result = detect_flaky_cases(store, suite="reasoning", mode="deterministic_software", last_n=5)
            self.assertFalse(result.get("ok"))
            self.assertEqual(result.get("error"), "no_eval_runs")
            self.assertEqual(result.get("runs_considered"), 0)

    def test_agent_reach_install_empty_stdout_fails(self) -> None:
        import importlib.util

        path = ROOT / "plugins" / "agent-reach" / "hades_bridge.py"
        spec = importlib.util.spec_from_file_location("agent_reach_bridge", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with patch.object(
            mod,
            "run",
            return_value={"exit_code": 0, "stdout": "", "stderr": "", "command": ["agent-reach"]},
        ):
            with patch("sys.argv", ["hades_bridge.py", "install_check", "--env", "auto"]):
                code = mod.main()
        self.assertNotEqual(code, 0)

        overlay = ROOT / "plugins" / "agent-reach" / "overlay" / "hades_bridge.py"
        overlay_text = overlay.read_text(encoding="utf-8")
        self.assertIn("agent-reach install_check produced empty output", overlay_text)
        self.assertIn('payload = {**payload, "ok": True, "exit_code": 0}', overlay_text)


if __name__ == "__main__":
    unittest.main()
