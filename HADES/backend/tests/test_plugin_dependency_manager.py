from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from platform_services import PluginManager


class ObservablePluginManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "hades.db"))
        self.db.initialize()
        self.manager = PluginManager(self.db, self.root / "data")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_plugin(self, dependency_install: dict[str, int] | None = None) -> str:
        source = self.root / "observable-plugin"
        source.mkdir(exist_ok=True)
        (source / "echo.py").write_text("print('ok')\n", encoding="utf-8")
        manifest = {
            "format": 1,
            "id": "observable-plugin",
            "name": "Observable Plugin",
            "version": "1.0.0",
            "runtime_type": "python",
            "permissions": ["subprocess"],
            "tools": [
                {
                    "name": "echo",
                    "action": "run",
                    "command": ["{python}", "echo.py"],
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        }
        if dependency_install is not None:
            manifest["dependency_install"] = dependency_install
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        converted = self.manager.import_local_folder(source, install_dependencies=False)
        return converted["plugin"]["id"]

    def test_manifest_can_override_dependency_limits_without_global_settings(self) -> None:
        plugin_id = self.make_plugin({"timeout_seconds": 321, "stall_timeout_seconds": 123})
        self.assertEqual(self.manager._dependency_limits(plugin_id, "python"), (321, 123))

    def test_runtime_defaults_are_longer_than_legacy_ten_minute_node_timeout(self) -> None:
        plugin_id = self.make_plugin()
        timeout, stall = self.manager._dependency_limits(plugin_id, "node")
        self.assertEqual(timeout, 1800)
        self.assertEqual(stall, 600)

    def test_dependency_status_is_available_before_first_install(self) -> None:
        plugin_id = self.make_plugin()
        status = self.manager.dependency_status(plugin_id)
        self.assertEqual(status["plugin_id"], plugin_id)
        self.assertEqual(status["state"]["phase"], "idle")
        self.assertEqual(status["log"], "")
        self.assertEqual(status["log_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
