import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "_shared"))

from pack_lib import pack_local
from platform_db import PlatformDatabase
from platform_services import PluginManager
from tests.plugin_package_helpers import is_git_lfs_pointer


class HypitPluginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = PlatformDatabase(str(self.root / "hades.db"))
        self.db.initialize()
        self.repo_root = Path(__file__).resolve().parents[2]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _plugin_dir(self) -> Path:
        return self.repo_root / "plugins" / "hypit"

    def _package_path(self) -> Path:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        package = plugin_dir / "dist" / f"{manifest['id']}-{manifest['version']}.HadesPlugin"
        if package.is_file() and not is_git_lfs_pointer(package):
            return package
        return pack_local(plugin_dir=plugin_dir, out_dir=self.root)

    def _import_fixture(self, *, install_dependencies: bool = True) -> dict:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        source = self.root / "hypit-fixture"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(
            plugin_dir,
            source,
            ignore=shutil.ignore_patterns("dist", "overlay", "pack_hadesplugin.py", "tests", ".hades-vendor"),
        )
        (source / "hades-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        manager = PluginManager(self.db, self.root / "data")
        return manager.import_local_folder(source, install_dependencies=install_dependencies)

    def test_manifest_shape(self) -> None:
        plugin_dir = self._plugin_dir()
        manifest = json.loads((plugin_dir / "hades-plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "hypit")
        self.assertEqual(manifest["runtime_type"], "python")
        self.assertTrue(manifest.get("autonomous"))
        self.assertEqual(manifest["source"], "https://github.com/hypit-ai/hypit")
        tool_names = {tool["name"] for tool in manifest["tools"]}
        self.assertTrue(
            {
                "doctor",
                "prepare",
                "list_skills",
                "get_skill",
                "inspect_source",
                "version",
                "check",
                "plan",
                "runtime_init",
                "build",
            }.issubset(tool_names),
            sorted(tool_names),
        )
        prepare = next(tool for tool in manifest["tools"] if tool["name"] == "prepare")
        self.assertFalse(prepare.get("autonomous", True))
        build = next(tool for tool in manifest["tools"] if tool["name"] == "build")
        self.assertFalse(build.get("autonomous", True))

    def test_import_ready_and_knowledge_tools(self) -> None:
        converted = self._import_fixture(install_dependencies=False)
        plugin = converted["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        self.assertFalse(plugin["enabled"])
        manager = PluginManager(self.db, self.root / "data")
        self.db.set_plugin_state(plugin["id"], enabled=True)

        doctor = manager.invoke(plugin["id"], "doctor", {}, approved_by_user=True)
        self.assertEqual(doctor["status"], "completed", doctor.get("stderr") or doctor.get("error"))
        doctor_payload = json.loads(doctor["stdout"])
        self.assertTrue(doctor_payload["ok"], doctor_payload)
        self.assertTrue(doctor_payload["skills"]["present"])

        skills = manager.invoke(plugin["id"], "list_skills", {"limit": 50}, approved_by_user=True)
        self.assertEqual(skills["status"], "completed", skills.get("stderr") or skills.get("error"))
        skills_payload = json.loads(skills["stdout"])
        self.assertGreater(skills_payload["count"], 0)
        skill_blob = json.dumps(skills_payload).lower()
        self.assertIn("hypit", skill_blob)

        loaded = manager.invoke(
            plugin["id"],
            "get_skill",
            {"skill": "hypit", "max_chars": 4000},
            approved_by_user=True,
        )
        self.assertEqual(loaded["status"], "completed", loaded.get("stderr") or loaded.get("error"))
        loaded_payload = json.loads(loaded["stdout"])
        self.assertIn("Hypit", loaded_payload.get("content") or "")

        examples = manager.invoke(plugin["id"], "list_examples", {"limit": 20}, approved_by_user=True)
        self.assertEqual(examples["status"], "completed", examples.get("stderr") or examples.get("error"))
        example_payload = json.loads(examples["stdout"])
        self.assertTrue(example_payload["ok"], example_payload)
        inspect = manager.invoke(
            plugin["id"],
            "inspect_source",
            {"path": "fixtures/chat.svml", "max_chars": 2000},
            approved_by_user=True,
        )
        self.assertEqual(inspect["status"], "completed", inspect.get("stderr") or inspect.get("error"))
        inspect_payload = json.loads(inspect["stdout"])
        self.assertTrue(inspect_payload["ok"], inspect_payload)
        self.assertFalse(inspect_payload["compiled"])
        self.assertEqual(inspect_payload["kind"], "author")

    def test_cli_tools_fail_closed_without_hypit(self) -> None:
        converted = self._import_fixture(install_dependencies=False)
        plugin = converted["plugin"]
        manager = PluginManager(self.db, self.root / "data")
        self.db.set_plugin_state(plugin["id"], enabled=True)
        version = manager.invoke(plugin["id"], "version", {}, approved_by_user=True)
        out = version.get("stdout") or version.get("output") or ""
        payload = json.loads(out)
        if payload.get("ok"):
            # Host already has hypit on PATH / vendor — still a valid HADES invoke.
            self.assertTrue(payload.get("version") or payload.get("stdout"))
            self.assertEqual(version["status"], "completed")
            return
        self.assertEqual(version["status"], "failed", version.get("error"))
        self.assertFalse(payload.get("ok"))
        self.assertIn("hypit_cli_missing", str(payload.get("error") or payload))

    def test_import_zip_package_roundtrip(self) -> None:
        package = self._package_path()
        self.assertTrue(package.is_file())
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
        self.assertIn("hades-plugin.json", names)
        self.assertIn("source/hades_bridge.py", names)
        manager = PluginManager(self.db, self.root / "data")
        imported = manager.import_zip(package, install_dependencies=False)
        plugin = imported["plugin"]
        self.assertEqual(plugin["status"], "ready", plugin.get("last_error"))
        self.db.set_plugin_state(plugin["id"], enabled=True)
        doctor = manager.invoke(plugin["id"], "doctor", {}, approved_by_user=True)
        self.assertIn(doctor["status"], {"completed", "failed"})
        payload = json.loads(doctor["stdout"])
        self.assertIn("ok", payload)

    def test_prepare_installs_cli_when_npm_available(self) -> None:
        """Live path: HADES invoke prepare then version against real @hypit/hypit."""
        converted = self._import_fixture(install_dependencies=False)
        plugin = converted["plugin"]
        manager = PluginManager(self.db, self.root / "data")
        self.db.set_plugin_state(plugin["id"], enabled=True)
        workdir = Path(plugin["local_path"])
        vendor = workdir / ".hades-vendor"
        if vendor.exists():
            shutil.rmtree(vendor)
        npm_vendor = Path("/tmp/hypit-npm/node_modules/@hypit/hypit/bin/hypit.mjs")
        if npm_vendor.is_file():
            # Reuse the already-fetched package so the test does not depend on npm registry.
            vendor.mkdir(parents=True, exist_ok=True)
            (vendor / "package.json").write_text(
                json.dumps({"name": "hades-hypit-vendor", "private": True, "dependencies": {"@hypit/hypit": "0.1.9"}}),
                encoding="utf-8",
            )
            shutil.copytree(npm_vendor.parents[3], vendor / "node_modules", dirs_exist_ok=True)
        prepared = manager.invoke(plugin["id"], "prepare", {"pin": "0.1.9"}, approved_by_user=True, timeout=120)
        out = prepared.get("stdout") or prepared.get("output") or ""
        if not out.strip():
            self.skipTest(f"prepare produced no JSON: {prepared.get('error')}")
        payload = json.loads(out)
        err = str(payload.get("error") or prepared.get("error") or "").lower()
        if not payload.get("ok") and any(token in err for token in ("npm_missing", "node_missing", "npm_install", "network", "enotfound", "timeout")):
            self.skipTest(f"host cannot install @hypit/hypit: {err}")
        self.assertEqual(prepared["status"], "completed", prepared.get("stderr") or prepared.get("error") or out)
        self.assertTrue(payload.get("ok"), payload)
        version = manager.invoke(plugin["id"], "version", {}, approved_by_user=True)
        self.assertEqual(version["status"], "completed", version.get("stderr") or version.get("error"))
        version_payload = json.loads(version["stdout"])
        self.assertTrue(version_payload.get("ok"), version_payload)
        self.assertEqual(str(version_payload.get("version")), "0.1.9")
        paths = manager.invoke(plugin["id"], "paths", {"workspace": str(workdir)}, approved_by_user=True)
        self.assertEqual(paths["status"], "completed", paths.get("stderr") or paths.get("error"))
        paths_payload = json.loads(paths["stdout"])
        self.assertTrue(paths_payload.get("ok"), paths_payload)
        self.assertIn("project", paths_payload)


if __name__ == "__main__":
    unittest.main()
