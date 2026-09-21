#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class MarkitdownDoctorTests(unittest.TestCase):
    def test_doctor_exit_matches_ok(self) -> None:
        proc = subprocess.run([sys.executable, str(ROOT / "hades_bridge.py"), "doctor"], capture_output=True, text=True)
        payload = json.loads(proc.stdout)
        if payload.get("ok", True):
            self.assertEqual(proc.returncode, 0)
        else:
            self.assertNotEqual(proc.returncode, 0)

if __name__ == "__main__":
    unittest.main()
