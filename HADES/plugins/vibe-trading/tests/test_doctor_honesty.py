#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class VibeTradingDoctorTests(unittest.TestCase):
    def test_doctor_missing_cli_is_nonzero(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "hades_bridge.py"), "doctor"],
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertIsNone(payload.get("cli"))
        self.assertNotEqual(proc.returncode, 0)

    def test_research_empty_stdout_is_nonzero(self) -> None:
        sys.path.insert(0, str(ROOT))
        import hades_bridge

        with patch.object(hades_bridge, "_binary", return_value="/usr/bin/true"), patch(
            "subprocess.run"
        ) as run:
            run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            payload = hades_bridge.research("hello", 5)
        # Direct function still returns raw payload; main() gates empty stdout.
        self.assertEqual(payload.get("exit_code"), 0)
        self.assertEqual(payload.get("stdout"), "")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "hades_bridge.py"), "research", "--prompt", "x"],
            capture_output=True,
            text=True,
            env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PATH": "/usr/bin:/bin"},
        )
        # Without vibe-trading on PATH, research fails closed.
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
