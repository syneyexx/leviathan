from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tools.hades_tray import TrayRuntime, tray_supported


class HadesTrayRuntimeTests(unittest.TestCase):
    def test_open_ui_uses_webbrowser(self) -> None:
        runtime = TrayRuntime(root=Path("."), frontend_url="http://127.0.0.1:3000")
        with mock.patch("tools.hades_tray.webbrowser.open") as open_ui:
            runtime.open_ui()
        open_ui.assert_called_once_with("http://127.0.0.1:3000")

    def test_quit_terminates_tracked_processes(self) -> None:
        runtime = TrayRuntime(root=Path("."))
        proc = mock.Mock(spec=subprocess.Popen)
        proc.poll.return_value = None
        runtime.track("backend", proc)
        runtime.quit_hades()
        self.assertTrue(runtime.quit_requested)
        proc.terminate.assert_called_once()

    def test_tray_supported_flag_matches_platform(self) -> None:
        # Honesty: tray host is Windows-first; other OS must not pretend ready.
        self.assertEqual(tray_supported(), __import__("os").name == "nt")


if __name__ == "__main__":
    unittest.main()
