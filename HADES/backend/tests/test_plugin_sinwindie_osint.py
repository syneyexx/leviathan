import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_db import PlatformDatabase
from platform_services import PluginManager
from tests.plugin_package_helpers import is_git_lfs_pointer, write_overlay_hadesplugin


class SinwindieOsintPluginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "hades.db"))
        self.db.initialize()
        self.repo_root = Path(__file__).resolve().parents[2]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _plugin_dir(self) -> Path:
        return self.repo_root / "plugins" / "sinwindie-osint"

    def _package_path(self) -> Path:
        plugin_dir = self._plugin_dir()
        package = plugin_dir / "dist" / "sinwindie-osint-0.1.0.HadesPlugin"
        if package.is_file() and not is_git_lfs_pointer(package):
            return package
        local = self.root / "sinwindie-osint-0.1.0.HadesPlugin"
        return write_overlay_hadesplugin(
            plugin_dir,
            local,
            files=[
                "hades_bridge.py",
                "cli_bridge.py",
                "requirements.txt",
                "sultan_sites.json",
                "catalog.json",
                "bookmarklets.json",
            ],
        )

    def _import_fixture(self, *, install_dependencies: bool = True) -> dict:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        source = self.root / "sinwindie-fixture"
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        for name in (
            "hades_bridge.py",
            "cli_bridge.py",
            "requirements.txt",
            "sultan_sites.json",
            "catalog.json",
            "bookmarklets.json",
        ):
            src = plugin_dir / name
            self.assertTrue(src.is_file(), name)
            shutil.copy2(src, source / name)
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        manager = PluginManager(self.db, self.root / "data")
        return manager.import_local_folder(source, install_dependencies=install_dependencies)

    def test_manifest_and_package(self) -> None:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "sinwindie-osint")
        self.assertFalse(manifest.get("autonomous", True))
        names = {tool["name"] for tool in manifest["tools"]}
        self.assertEqual(
            names,
            {"doctor", "search_username", "list_sites", "list_topics", "list_bookmarklets", "get_bookmarklet"},
        )
        package = self._package_path()
        self.assertTrue(package.is_file())
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
            self.assertIn("hades-plugin.json", names)
            self.assertIn("source/hades_bridge.py", names)
            self.assertIn("source/sultan_sites.json", names)

    def test_import_and_invoke_list_and_search(self) -> None:
        converted = self._import_fixture(install_dependencies=False)
        plugin = converted["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        manager = PluginManager(self.db, self.root / "data")
        self.db.set_plugin_state(plugin["id"], enabled=True)

        topics = manager.invoke(plugin["id"], "list_topics", {"query": "Twitter"}, approved_by_user=True)
        self.assertEqual(topics["status"], "completed", topics.get("stderr") or topics.get("error"))
        payload = json.loads(topics["stdout"])
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["count"], 1)

        sites = manager.invoke(plugin["id"], "list_sites", {"category": "Social Media"}, approved_by_user=True)
        self.assertEqual(sites["status"], "completed", sites.get("stderr") or sites.get("error"))
        sites_payload = json.loads(sites["stdout"])
        self.assertGreater(sites_payload["count"], 0)

        # Bounded live probe — network optional; allow soft skip on total network failure.
        search = manager.invoke(
            plugin["id"],
            "search_username",
            {"username": "github", "category": "Social Media", "max_sites": 3, "timeout": 8, "workers": 3},
            approved_by_user=True,
        )
        self.assertEqual(search["status"], "completed", search.get("stderr") or search.get("error"))
        search_payload = json.loads(search["stdout"])
        self.assertTrue(search_payload["ok"])
        self.assertEqual(search_payload["checked"], 3)


if __name__ == "__main__":
    unittest.main()
