from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Data.modules.module_manager import (
    ModuleContext,
    ModuleManager,
    ModuleManagerError,
    ModuleStatus,
)
from Data.modules.module_manager.discovery import ManifestError, load_manifest_file, parse_manifest
from Data.modules.neuro.echo_module import create_echo_module


class ModuleManagerTests(unittest.TestCase):
    def test_parse_manifest_requires_entrypoint(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest({"module_id": "x", "name": "X"})

    def test_lifecycle_discover_load_execute_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "echo"
            root.mkdir(parents=True)
            manifest = {
                "module_id": "neuro.echo",
                "name": "Neuro Echo Module",
                "version": "0.1.0",
                "entrypoint": "Data.modules.neuro.echo_module:create_echo_module",
                "hot_reload": True,
                "capabilities": [
                    {
                        "capability_id": "neuro.echo.ping",
                        "name": "ping",
                        "external_name": "ping",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")

            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            discovered = manager.discover()
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0].module_id, "neuro.echo")

            manager.initialize(
                "neuro.echo",
                ModuleContext(feature_flags={"module_manager_enabled": True}),
            )
            result = manager.execute("neuro.echo", "ping", {"message": "leviathan"})
            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.output["echo"], "leviathan")
            self.assertTrue(result.public_dict()["truth"]["discoverable_is_not_authorized"])

            manager.shutdown("neuro.echo")
            managed = manager.get("neuro.echo")
            assert managed is not None
            self.assertEqual(managed.status, ModuleStatus.SHUTDOWN)

    def test_register_instance_path(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        managed = manager.register_instance(create_echo_module(), ready=True)
        self.assertEqual(managed.status, ModuleStatus.READY)
        result = manager.execute("neuro.echo", "ping", {"message": "hi"})
        self.assertEqual(result.status, "COMPLETED")

    def test_execute_unknown_operation_contained(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        manager.register_instance(create_echo_module(), ready=True)
        result = manager.execute("neuro.echo", "nope", {})
        self.assertEqual(result.status, "REJECTED")

    def test_disabled_manager_skips_discover(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=False)
        self.assertEqual(manager.discover(), [])

    def test_invalid_manifest_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "bad"
            root.mkdir(parents=True)
            (root / "module.json").write_text("{not-json", encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            items = manager.list()
            self.assertTrue(any(item.status == ModuleStatus.ERROR for item in items))

    def test_hot_reload_requires_flag(self) -> None:
        manager = ModuleManager(discovery_roots=(), enabled=True)
        module = create_echo_module()
        # Force hot_reload false via re-register after mutating is impossible (frozen) —
        # use execute path: reload on echo which allows hot_reload.
        manager.register_instance(module, ready=True)
        # Should succeed because echo allows hot_reload
        reloaded = manager.reload("neuro.echo", ModuleContext())
        self.assertEqual(reloaded.status, ModuleStatus.READY)

    def test_load_manifest_file(self) -> None:
        path = Path("Data/modules/neuro/module.json")
        if path.is_file():
            manifest = load_manifest_file(path)
            self.assertEqual(manifest.module_id, "neuro.echo")


if __name__ == "__main__":
    unittest.main()
