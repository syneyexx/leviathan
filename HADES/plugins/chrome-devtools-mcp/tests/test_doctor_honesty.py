#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys, unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class ChromeDevtoolsDoctorTests(unittest.TestCase):
    def test_doctor_without_npx_is_nonzero(self) -> None:
        env_patch = patch("shutil.which", return_value=None)
        # Run as importable module path via subprocess with PYTHONPATH and a tiny wrapper is heavy;
        # instead execute doctor() directly.
        sys.path.insert(0, str(ROOT))
        import hades_bridge
        with patch.object(hades_bridge.shutil, "which", return_value=None):
            payload = hades_bridge.doctor()
        self.assertFalse(payload.get("ok"))
        self.assertIn("missing_required", str(payload.get("error") or ""))

if __name__ == "__main__":
    unittest.main()
