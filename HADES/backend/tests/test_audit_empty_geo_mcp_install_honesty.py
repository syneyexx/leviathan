"""GhostTrack empty geolocation and MCP/browser install empty-success honesty."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class GhostTrackEmptyGeoHonestyTests(unittest.TestCase):
    def test_track_ip_empty_geo_not_ok(self) -> None:
        bridge = _load("gt_track_honesty", REPO / "plugins" / "ghosttrack" / "hades_bridge.py")
        with mock.patch.object(
            bridge,
            "http_get_json",
            return_value={
                "success": True,
                "latitude": None,
                "longitude": None,
                "country": None,
                "connection": {},
            },
        ):
            payload = bridge.track_ip("1.2.3.4")
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "empty_geolocation")


class McpExpandEmptyHonestyTests(unittest.TestCase):
    def test_expand_return_marks_zero_remote_tools_not_ok(self) -> None:
        source = (REPO / "backend" / "platform_services_core.py").read_text(encoding="utf-8")
        self.assertIn('"error": "no_remote_mcp_tools"', source)
        self.assertIn('"ok": False', source)
        main = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn('result.get("ok") is False', main)
        self.assertIn("MCP-expansie leverde geen tools op", main)

    def test_plugins_page_does_not_green_toast_zero_expand(self) -> None:
        page = (REPO / "components" / "hades" / "pages" / "plugins-page-core.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("expansion.ok === false || expanded <= 0", page)
        self.assertIn("toast.error", page)


class BrowserInstallHonestyTests(unittest.TestCase):
    def test_scrapling_install_browsers_has_ok(self) -> None:
        bridge = _load("scrapling_install_honesty", REPO / "plugins" / "scrapling" / "hades_bridge.py")
        with mock.patch.object(bridge.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
            with mock.patch.object(bridge.shutil, "which", return_value="scrapling"):
                payload = bridge.install_browsers()
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "browser_install_failed")

    def test_patchright_install_browsers_has_ok(self) -> None:
        bridge = _load(
            "patchright_install_honesty", REPO / "plugins" / "patchright" / "hades_bridge.py"
        )
        with mock.patch.object(bridge.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
            payload = bridge.install_browsers()
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "browser_install_failed")


if __name__ == "__main__":
    unittest.main()
