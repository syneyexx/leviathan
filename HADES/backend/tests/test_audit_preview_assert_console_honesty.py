"""Preview flows must not greenwash assert_visible/console or overclaim DOM tools."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PreviewAssertConsoleHonestyTests(unittest.TestCase):
    def test_capabilities_require_real_tools(self) -> None:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=MagicMock())
        adapter._plugin_availability = MagicMock(  # type: ignore
            return_value={
                "available": True,
                "tools": ["fetch", "screenshot"],
            }
        )
        caps = adapter.capabilities()
        self.assertTrue(caps.get("open_page") or caps.get("screenshot"))
        self.assertFalse(caps.get("fill"))
        self.assertFalse(caps.get("click"))
        self.assertFalse(caps.get("console_errors"))

    def test_assert_visible_is_not_screenshot_success(self) -> None:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=MagicMock())
        adapter._plugin_availability = MagicMock(return_value={"available": True, "tools": ["fetch", "screenshot"]})  # type: ignore
        adapter.open_page = MagicMock(return_value={"ok": True, "status": "opened"})  # type: ignore
        adapter.screenshot = MagicMock(return_value={"ok": True, "status": "captured", "artifact": "a.png"})  # type: ignore
        out = adapter.run_user_flow(
            url="http://127.0.0.1:9/",
            steps=[{"action": "assert_visible", "selector": "#x"}],
            change_hash="h",
            out_dir=tempfile.mkdtemp(),
        )
        self.assertFalse(out.get("ok"))
        self.assertGreaterEqual(int(out.get("failed_steps") or 0), 1)

    def test_console_step_is_unavailable_not_success(self) -> None:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=MagicMock())
        adapter._plugin_availability = MagicMock(return_value={"available": True, "tools": ["fetch", "screenshot"]})  # type: ignore
        adapter.open_page = MagicMock(return_value={"ok": True, "status": "opened"})  # type: ignore
        adapter.screenshot = MagicMock(return_value={"ok": True, "status": "captured", "artifact": "a.png"})  # type: ignore
        out = adapter.run_user_flow(
            url="http://127.0.0.1:9/",
            steps=[{"action": "console_errors"}],
            change_hash="h",
            out_dir=tempfile.mkdtemp(),
        )
        self.assertFalse(out.get("ok"))


if __name__ == "__main__":
    unittest.main()
