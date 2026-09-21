#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NetstrikerDoctorTests(unittest.TestCase):
    def test_doctor_missing_backend_layout_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "hades_bridge.py"
            bridge.write_text((ROOT / "hades_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            # No backend/ beside the bridge copy.
            proc = subprocess.run([sys.executable, str(bridge), "doctor"], capture_output=True, text=True)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("missing_required_layout", str(payload.get("error") or ""))

    def test_doctor_layout_ok_but_modules_missing_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge = root / "hades_bridge.py"
            bridge.write_text((ROOT / "hades_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            backend = root / "backend"
            backend.mkdir()
            # Match filenames checked by doctor() layout dict.
            for name in ("scanner.py", "remediation.py", "compliance.py", "server.py"):
                (backend / name).write_text("# fixture\n", encoding="utf-8")
            (root / "cli_bridge.py").write_text(
                "def doctor(modules, binaries):\n"
                "    return {'ok': False, 'error': 'missing_modules:' + ','.join(modules), 'modules': []}\n",
                encoding="utf-8",
            )
            proc = subprocess.run([sys.executable, str(bridge), "doctor"], capture_output=True, text=True)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload.get("ok"), payload)
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
