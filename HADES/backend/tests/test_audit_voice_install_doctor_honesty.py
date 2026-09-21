"""Voice install must not report ok when doctor is not ready."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class VoiceInstallDoctorHonestyTests(unittest.TestCase):
    def test_run_install_requires_doctor_ready(self) -> None:
        from voice import install as voice_install

        source = inspect.getsource(voice_install.run_install)
        self.assertIn("doctor(", source)
        self.assertIn("voice_doctor_not_ready", source)
        self.assertIn("ready = bool(health.get(\"ready\"))", source)
        self.assertIn('"ok": ready', source)


if __name__ == "__main__":
    unittest.main()
