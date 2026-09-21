#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliBridgeDoctorHonestyTests(unittest.TestCase):
    def test_missing_module_is_nonzero(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "cli_bridge.py"), "doctor", "--modules", "definitely_missing_xyz"],
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertNotEqual(proc.returncode, 0)

    def test_no_requirements_is_ok(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "cli_bridge.py"), "doctor"],
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
