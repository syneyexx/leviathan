"""Launcher lifecycle termination tests (no Windows Job Object required)."""

from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import MagicMock

from tools.launcher_lifecycle import LauncherLifecycle, transactional_startup_failed


class LauncherLifecycleTests(unittest.TestCase):
    def test_terminate_tracked_process(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        life = LauncherLifecycle()
        life.track("child", proc)
        self.assertIsNone(proc.poll())
        report = transactional_startup_failed(life, reason="readiness_timeout")
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "readiness_timeout")
        self.assertFalse(report["orphan_alive"])
        self.assertIsNotNone(proc.poll())

    def test_note_denies_sandbox_claim(self) -> None:
        life = LauncherLifecycle()
        self.assertIn("not_sandbox", life.note)


if __name__ == "__main__":
    unittest.main()
