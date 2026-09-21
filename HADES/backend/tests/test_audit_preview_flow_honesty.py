"""BrowserAdapter.run_user_flow must not succeed when later steps fail."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PreviewFlowHonestyTests(unittest.TestCase):
    def test_failed_click_fails_flow_even_if_open_ok(self) -> None:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=MagicMock())
        adapter._plugin_availability = MagicMock(return_value={"available": True})  # type: ignore
        adapter.open_page = MagicMock(return_value={"ok": True, "status": "opened"})  # type: ignore
        adapter.screenshot = MagicMock(  # type: ignore
            return_value={"ok": True, "status": "captured", "artifact": "shot.png"}
        )
        adapter.click = MagicMock(  # type: ignore
            return_value={"ok": False, "status": "failed", "reason": "selector_missing"}
        )
        out_dir = tempfile.mkdtemp()
        flow = adapter.run_user_flow(
            url="http://127.0.0.1:9/",
            steps=[{"action": "click", "selector": "#go"}],
            change_hash="abc",
            out_dir=out_dir,
        )
        self.assertFalse(flow.get("ok"))
        self.assertEqual(flow.get("status"), "failed")
        self.assertGreaterEqual(int(flow.get("failed_steps") or 0), 1)
        self.assertFalse(flow.get("live_host_pass"))

    def test_all_steps_ok_marks_executed(self) -> None:
        from preview_runtime import BrowserAdapter

        adapter = BrowserAdapter(plugin_manager=MagicMock())
        adapter._plugin_availability = MagicMock(return_value={"available": True})  # type: ignore
        adapter.open_page = MagicMock(return_value={"ok": True, "status": "opened"})  # type: ignore
        adapter.screenshot = MagicMock(  # type: ignore
            return_value={"ok": True, "status": "captured", "artifact": "shot.png"}
        )
        adapter.click = MagicMock(return_value={"ok": True, "status": "clicked"})  # type: ignore
        out_dir = tempfile.mkdtemp()
        flow = adapter.run_user_flow(
            url="http://127.0.0.1:9/",
            steps=[{"action": "click", "selector": "#go"}],
            change_hash="abc",
            out_dir=out_dir,
        )
        self.assertTrue(flow.get("ok"))
        self.assertEqual(flow.get("status"), "executed")
        self.assertEqual(int(flow.get("failed_steps") or 0), 0)


if __name__ == "__main__":
    unittest.main()
