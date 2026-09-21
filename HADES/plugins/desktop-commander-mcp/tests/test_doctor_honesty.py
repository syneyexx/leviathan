#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class DesktopCommanderDoctorTests(unittest.TestCase):
    def test_doctor_without_npx_is_nonzero(self) -> None:
        sys.path.insert(0, str(ROOT))
        import hades_bridge
        with patch.object(hades_bridge.shutil, "which", return_value=None):
            payload = hades_bridge.doctor()
        self.assertFalse(payload.get("ok"))
        self.assertIn("missing_required", str(payload.get("error") or ""))

if __name__ == "__main__":
    unittest.main()
