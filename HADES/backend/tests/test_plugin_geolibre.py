import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from platform_services import PluginManager
from reasoning import discover_tools


class GeoLibrePluginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "hades.db"))
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _import_geolibre_fixture(self) -> dict:
        repo_root = Path(__file__).resolve().parents[2]
        manifest_path = repo_root / "plugins" / "geolibre" / "hades-plugin.json"
        self.assertTrue(manifest_path.is_file(), "plugins/geolibre/hades-plugin.json ontbreekt")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        adapter = repo_root / "plugins" / "geolibre" / "geolibre_hades.py"
        self.assertTrue(adapter.is_file(), "plugins/geolibre/geolibre_hades.py ontbreekt")
        fixture = repo_root / "plugins" / "geolibre" / "fixtures" / "demo-cities.geojson"
        self.assertTrue(fixture.is_file(), "demo-cities fixture ontbreekt")

        source = self.root / "geolibre-fixture"
        source.mkdir()
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (source / "package.json").write_text(
            json.dumps(
                {
                    "name": "geolibre",
                    "version": "2.9.0",
                    "private": True,
                    "workspaces": ["apps/*"],
                    "engines": {"node": ">=22"},
                }
            ),
            encoding="utf-8",
        )
        (source / "geolibre_hades.py").write_text(adapter.read_text(encoding="utf-8"), encoding="utf-8")
        fixtures_dir = source / "fixtures"
        fixtures_dir.mkdir()
        (fixtures_dir / "demo-cities.geojson").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

        manager = PluginManager(self.db, self.root / "data")
        return manager.import_local_folder(source, install_dependencies=False)

    def test_geolibre_manifest_imports_with_data_and_service_tools(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        manifest = json.loads((repo_root / "plugins" / "geolibre" / "hades-plugin.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest.get("format"), 1)
        self.assertEqual(manifest.get("id"), "geolibre")
        self.assertEqual(manifest.get("version"), "0.2.0")
        self.assertTrue(manifest.get("autonomous", False))
        self.assertEqual(manifest.get("license"), "MIT")
        self.assertEqual(manifest.get("upstream_version"), "2.9.0")
        self.assertEqual(
            manifest.get("upstream_ref"),
            "cf02ccd881a3bc7b72f1af68a668dddffa0ffd7d",
        )
        self.assertEqual(manifest.get("healthcheck", {}).get("type"), "http")
        self.assertIn("5173", str(manifest.get("healthcheck", {}).get("url", "")))

        converted = self._import_geolibre_fixture()
        plugin = converted["plugin"]
        self.assertEqual(plugin["status"], "ready")
        self.assertFalse(plugin["enabled"])
        self.assertEqual(plugin["runtime_type"], "node")
        self.assertEqual(plugin["plugin_type"], "service")

        tool_names = {tool["name"] for tool in converted["tools"]}
        self.assertTrue(
            {
                "geolibre_inspect",
                "geolibre_analyze",
                "geolibre_load",
                "geolibre_list",
                "geolibre_query",
                "doctor",
                "start",
                "health",
                "status",
                "logs",
                "stop",
            }
            <= tool_names
        )
        start = next(tool for tool in converted["tools"] if tool["name"] == "start")
        self.assertEqual(start["metadata"].get("action"), "start")
        self.assertEqual(start["metadata"].get("mode"), "service")
        self.assertFalse(start["metadata"].get("autonomous", True))
        self.assertEqual(start["metadata"].get("env", {}).get("PORT"), "5173")
        self.assertIn("geolibre-desktop", start["command"])
        self.assertIn("--host", start["command"])

        query = next(tool for tool in converted["tools"] if tool["name"] == "geolibre_query")
        self.assertTrue(query["metadata"].get("autonomous", False))
        self.assertIn("geolibre_hades.py", query["command"])

    def test_geolibre_data_tools_are_invokable_and_usable(self) -> None:
        converted = self._import_geolibre_fixture()
        manager = PluginManager(self.db, self.root / "data")
        plugin_id = converted["plugin"]["id"]
        self.db.set_plugin_state(plugin_id, enabled=True)
        fixture_path = str(Path(converted["plugin"]["local_path"]) / "fixtures" / "demo-cities.geojson")

        loaded = manager.invoke(
            plugin_id,
            "geolibre_load",
            {"dataset_id": "demo-cities", "path": fixture_path, "title": "Demo cities"},
            approved_by_user=True,
        )
        self.assertEqual(loaded["status"], "completed", loaded.get("stderr") or loaded.get("error"))
        load_payload = json.loads(loaded["stdout"])
        self.assertTrue(load_payload["ok"])
        self.assertEqual(load_payload["feature_count"], 3)
        self.assertTrue(load_payload["hades_knowledge"])

        queried = manager.invoke(
            plugin_id,
            "geolibre_query",
            {
                "dataset_id": "demo-cities",
                "where": {"name": {"contains": "Amster"}},
                "geometry_types": ["Point"],
                "limit": 10,
            },
            approved_by_user=True,
        )
        self.assertEqual(queried["status"], "completed", queried.get("stderr") or queried.get("error"))
        query_payload = json.loads(queried["stdout"])
        self.assertEqual(query_payload["matched_features"], 1)
        self.assertEqual(query_payload["features"][0]["properties"]["name"], "Amsterdam")

        inline = manager.invoke(
            plugin_id,
            "geolibre_inspect",
            {
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "Inline"},
                            "geometry": {"type": "Point", "coordinates": [5.0, 52.0]},
                        }
                    ],
                }
            },
            approved_by_user=True,
        )
        self.assertEqual(inline["status"], "completed", inline.get("stderr") or inline.get("error"))
        inspect_payload = json.loads(inline["stdout"])
        self.assertEqual(inspect_payload["feature_count"], 1)

    def test_geolibre_lifecycle_tools_opt_out_of_autonomous_discovery(self) -> None:
        converted = self._import_geolibre_fixture()
        plugin = converted["plugin"]
        self.db.set_plugin_state(plugin["id"], enabled=True)
        plugin = self.db.get_plugin(plugin["id"])
        tools = self.db.plugin_tools(plugin["id"])
        discovered = discover_tools(
            query="geojson spatial query geolibre dataset",
            plugins=[plugin],
            tools=tools,
            permission_ok=lambda _plugin, _tool: True,
            include_unscored=True,
        )
        names = {item["tool_name"] for item in discovered["tools"]}
        self.assertIn("geolibre_query", names)
        self.assertIn("geolibre_load", names)
        self.assertNotIn("start", names)
        self.assertNotIn("stop", names)
        self.assertNotIn("doctor", names)


if __name__ == "__main__":
    unittest.main()
