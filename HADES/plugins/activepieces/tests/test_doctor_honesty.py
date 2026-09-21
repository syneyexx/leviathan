#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ActivepiecesDoctorTests(unittest.TestCase):
    def test_doctor_missing_compose_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "hades_bridge.py"
            bridge.write_text((ROOT / "hades_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            # Even with docker on PATH, missing compose must fail closed.
            with patch("shutil.which", return_value="/usr/bin/docker"):
                proc = subprocess.run([sys.executable, str(bridge), "doctor"], capture_output=True, text=True)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload.get("ok"))
            self.assertFalse(payload.get("compose_present"))
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
