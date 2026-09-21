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


class GhostTrackPluginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "hades.db"))
        self.db.initialize()
        self.repo_root = Path(__file__).resolve().parents[2]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _plugin_dir(self) -> Path:
        return self.repo_root / "plugins" / "ghosttrack"

    def _package_path(self) -> Path:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        package = plugin_dir / "dist" / f"{manifest['id']}-{manifest['version']}.HadesPlugin"
        if package.is_file() and not is_git_lfs_pointer(package):
            return package
        # Cloud/agent checkouts often keep LFS pointers only — pack overlay sources locally.
        local = self.root / f"{manifest['id']}-{manifest['version']}.HadesPlugin"
        return write_overlay_hadesplugin(
            plugin_dir,
            local,
            files=["hades_bridge.py", "cli_bridge.py", "requirements.txt", "GhostTR.py"],
        )

    def _import_fixture(self, *, install_dependencies: bool = True) -> dict:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        source = self.root / "ghosttrack-fixture"
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        for name in ("hades_bridge.py", "cli_bridge.py", "requirements.txt", "GhostTR.py"):
            src = plugin_dir / name
            if not src.is_file() and name == "GhostTR.py":
                # Fixture without full upstream pack still needs a stub for doctor/open_terminal checks.
                (source / "GhostTR.py").write_text("# stub GhostTR for tests\nprint('GhostTR stub')\n", encoding="utf-8")
                continue
            self.assertTrue(src.is_file(), f"missing {name}")
            shutil.copy2(src, source / name)
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        manager = PluginManager(self.db, self.root / "data")
        return manager.import_local_folder(source, install_dependencies=install_dependencies)

    def test_manifest_and_package_shape(self) -> None:
        plugin_dir = self._plugin_dir()
        manifest_path = plugin_dir / "hades-plugin.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "ghosttrack")
        self.assertEqual(manifest["runtime_type"], "python")
        self.assertFalse(manifest.get("autonomous", True))
        tool_names = {tool["name"] for tool in manifest["tools"]}
        self.assertEqual(
            tool_names,
            {"doctor", "track_ip", "show_ip", "track_phone", "track_username", "open_terminal"},
        )

        package = self._package_path()
        self.assertTrue(package.is_file(), "packed .HadesPlugin missing — run pack_hadesplugin.py")
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
            self.assertIn("hades-plugin.json", names)
            self.assertIn("source/hades_bridge.py", names)
            self.assertIn("source/GhostTR.py", names)
            self.assertIn("source/requirements.txt", names)

    def test_import_ready_and_track_phone_invoke(self) -> None:
        # Contract path uses overlay sources. Dependency install may fail offline —
        # tools must still run when host packages (e.g. phonenumbers) are available.
        converted = self._import_fixture(install_dependencies=False)
        plugin = converted["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        self.assertFalse(plugin["enabled"])
        manager = PluginManager(self.db, self.root / "data")
        self.db.set_plugin_state(plugin["id"], enabled=True)

        doctor = manager.invoke(plugin["id"], "doctor", {}, approved_by_user=True)
        self.assertEqual(doctor["status"], "completed", doctor.get("stderr") or doctor.get("error"))
        doctor_payload = json.loads(doctor["stdout"])
        self.assertTrue(doctor_payload["upstream"]["present"])

        phone = manager.invoke(
            plugin["id"],
            "track_phone",
            {"phone": "+31612345678", "default_region": "NL"},
            approved_by_user=True,
        )
        err = " ".join(
            str(phone.get(k) or "")
            for k in ("stderr", "error", "output", "stdout")
        ).lower()
        if phone.get("status") != "completed" and "phonenumbers" in err:
            self.skipTest("phonenumbers unavailable in plugin runtime (offline dep install)")
        self.assertEqual(phone["status"], "completed", phone.get("stderr") or phone.get("error") or phone.get("output") or phone.get("stdout"))
        payload = json.loads(phone["stdout"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["region_code"], "NL")
        self.assertEqual(payload["e164"], "+31612345678")

    def test_import_zip_package_roundtrip(self) -> None:
        package = self._package_path()
        self.assertTrue(package.is_file())
        manager = PluginManager(self.db, self.root / "data")
        imported = manager.import_zip(package, install_dependencies=False)
        plugin = imported["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        self.db.set_plugin_state(plugin["id"], enabled=True)
        result = manager.invoke(
            plugin["id"],
            "track_phone",
            {"phone": "+12025550123", "default_region": "US"},
            approved_by_user=True,
        )
        err = " ".join(str(result.get(k) or "") for k in ("stderr", "error", "output", "stdout")).lower()
        if result.get("status") != "completed" and "phonenumbers" in err:
            self.skipTest("phonenumbers unavailable in plugin runtime (offline dep install)")
        self.assertEqual(result["status"], "completed", result.get("stderr") or result.get("error") or result.get("stdout"))
        payload = json.loads(result["stdout"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["country_code"], 1)


if __name__ == "__main__":
    unittest.main()
