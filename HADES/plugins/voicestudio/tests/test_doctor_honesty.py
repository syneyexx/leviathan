"""Doctor honesty: VoiceStudio fails closed without Docker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hades_bridge  # noqa: E402


class VoicestudioDoctorHonestyTests(unittest.TestCase):
    def test_doctor_false_without_docker(self) -> None:
        with mock.patch.object(hades_bridge.shutil, "which", return_value=None):
            payload = hades_bridge.doctor()
        self.assertFalse(payload["ok"])
        self.assertFalse(payload.get("ready_to_start"))
        self.assertIn("docker", payload.get("error") or "")

    def test_doctor_cli_exits_nonzero_without_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "hades_bridge.py"
            bridge.write_text((ROOT / "hades_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
            env = {**os.environ, "PATH": "/nonexistent"}
            proc = subprocess.run(
                [sys.executable, str(bridge), "doctor"],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            payload = json.loads(proc.stdout)
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
