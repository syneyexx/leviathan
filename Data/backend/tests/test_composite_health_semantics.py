"""CompositeAdapter health aggregation — lifecycle truth, not false ERROR."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleStatus
from Data.modules.module_manager.external.adapters.base import AdapterContext
from Data.modules.module_manager.external.adapters.cli import CliAdapter
from Data.modules.module_manager.external.adapters.composite import CompositeAdapter
from Data.modules.module_manager.external.adapters.mcp_adapter import McpAdapter
from Data.modules.module_manager.external.adapters.skill_pack import SkillPackAdapter
from Data.modules.module_manager.external.types import ExternalRuntimeState, parse_external_config


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "external_capabilities"
FACTORY = "Data.modules.module_manager.external.module:create_external_capability_module"


def _write_composite_manifest(
    root: Path,
    *,
    module_id: str,
    children: list[str],
    tool: Path,
    skill_src: Path | None = None,
    eager_mcp: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if skill_src is not None:
        shutil.copytree(skill_src, root / "skills_src")
    external: dict[str, Any] = {
        "adapter": "COMPOSITE",
        "source_type": "path",
        "path": str(root / "skills_src") if skill_src is not None else str(root),
        "install": {"strategy": "NONE"},
        "children": children,
        "skill_roots": ["skills"],
        "runtime": {
            "command": [sys.executable, str(tool), "{query}"],
            "operations": [
                {"name": "search", "command": [sys.executable, str(tool), "{query}"]},
            ],
            "eager_start": eager_mcp,
        },
        "result": {"format": "json"},
    }
    if "MCP" in children:
        external["mcp"] = {"server_id": f"{module_id}-mcp"}
    manifest = {
        "module_id": module_id,
        "name": module_id,
        "version": "0.0.1",
        "entrypoint": FACTORY,
        "external": external,
        "capabilities": [
            {
                "capability_id": f"external.{module_id}.search",
                "name": "Search",
                "external_name": "search",
                "side_effects": ["READ"],
            }
        ],
    }
    (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")


class CompositeHealthSemanticsTests(unittest.TestCase):
    def test_required_ready_optional_skill_discovered_is_ready(self) -> None:
        """Executable child READY + optional skill DISCOVERED must not be ERROR."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "comp-ready-opt"
            tool = FIXTURES / "fake_cli" / "tool.py"
            _write_composite_manifest(
                root,
                module_id="comp-ready-opt",
                children=["SKILL_PACK", "CLI"],
                tool=tool,
                skill_src=FIXTURES / "fake_skill",
            )
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "comp-ready-opt",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("comp-ready-opt")
            manager.start("comp-ready-opt")

            # Force optional skill child back to DISCOVERED without touching CLI.
            instance = manager._modules["comp-ready-opt"].instance  # type: ignore[attr-defined]
            assert instance is not None
            adapter = instance._adapter  # type: ignore[attr-defined]
            assert isinstance(adapter, CompositeAdapter)
            for child in adapter._children:
                if isinstance(child, SkillPackAdapter):
                    child._state = ExternalRuntimeState.DISCOVERED
                    child._skills = []

            health = adapter.health()
            self.assertEqual(health.status, ModuleStatus.READY)
            self.assertNotIn(health.status, {ModuleStatus.ERROR, ModuleStatus.FAILED})
            roles = (health.telemetry or {}).get("child_roles") or []
            self.assertTrue(any(r.get("role") == "optional" and r.get("status") == "DISCOVERED" for r in roles))

    def test_required_child_failed_remains_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "comp-fail"
            tool = FIXTURES / "fake_cli" / "tool.py"
            _write_composite_manifest(
                root,
                module_id="comp-fail",
                children=["SKILL_PACK", "CLI"],
                tool=tool,
                skill_src=FIXTURES / "fake_skill",
            )
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "comp-fail",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("comp-fail")
            instance = manager._modules["comp-fail"].instance  # type: ignore[attr-defined]
            adapter = instance._adapter  # type: ignore[attr-defined]
            assert isinstance(adapter, CompositeAdapter)

            for child in adapter._children:
                if isinstance(child, CliAdapter):
                    child._state = ExternalRuntimeState.FAILED
                    child.ensure_ready = lambda: {"ready": False, "code": "COMMAND_FAILED"}  # type: ignore[method-assign]

            health = adapter.health()
            self.assertIn(health.status, {ModuleStatus.FAILED, ModuleStatus.ERROR})

    def test_not_installed_composite_is_discovered_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "comp-ni"
            # Point CLI at a missing install path so ensure_ready reports NOT_INSTALLED.
            tool = Path(tmp) / "missing" / "tool.py"
            _write_composite_manifest(
                root,
                module_id="comp-ni",
                children=["SKILL_PACK", "CLI"],
                tool=tool,
                skill_src=None,
            )
            # Override path to non-existent install target.
            manifest_path = root / "module.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["external"]["path"] = str(Path(tmp) / "does-not-exist")
            data["external"]["source_type"] = "path"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")

            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "comp-ni",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            # Do not install — health must reflect lifecycle, not ERROR.
            instance = manager._modules["comp-ni"].instance  # type: ignore[attr-defined]
            adapter = instance._adapter  # type: ignore[attr-defined]
            assert isinstance(adapter, CompositeAdapter)
            health = adapter.health()
            self.assertNotIn(health.status, {ModuleStatus.ERROR, ModuleStatus.FAILED})
            self.assertIn(
                health.status,
                {ModuleStatus.DISCOVERED, ModuleStatus.INSTALLED, ModuleStatus.STOPPED, ModuleStatus.DISABLED},
            )

    def test_fully_ready_composite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "comp-ok"
            tool = FIXTURES / "fake_cli" / "tool.py"
            _write_composite_manifest(
                root,
                module_id="comp-ok",
                children=["SKILL_PACK", "CLI"],
                tool=tool,
                skill_src=FIXTURES / "fake_skill",
            )
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "comp-ok",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("comp-ok")
            manager.start("comp-ok")
            health = manager.health("comp-ok")
            self.assertEqual(health.status, ModuleStatus.READY)

    def test_optional_child_fatal_yields_degraded_when_required_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "comp-deg"
            tool = FIXTURES / "fake_cli" / "tool.py"
            _write_composite_manifest(
                root,
                module_id="comp-deg",
                children=["SKILL_PACK", "CLI"],
                tool=tool,
                skill_src=FIXTURES / "fake_skill",
            )
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "comp-deg",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("comp-deg")
            manager.start("comp-deg")
            instance = manager._modules["comp-deg"].instance  # type: ignore[attr-defined]
            adapter = instance._adapter  # type: ignore[attr-defined]
            assert isinstance(adapter, CompositeAdapter)
            for child in adapter._children:
                if isinstance(child, SkillPackAdapter):
                    child._state = ExternalRuntimeState.FAILED

            health = adapter.health()
            self.assertEqual(health.status, ModuleStatus.DEGRADED)

    def test_lazy_mcp_disconnected_is_optional_not_fatal(self) -> None:
        cfg = parse_external_config(
            {
                "adapter": "COMPOSITE",
                "children": ["MCP", "CLI"],
                "source_type": "none",
                "install": {"strategy": "NONE"},
                "runtime": {
                    "eager_start": False,
                    "command": [sys.executable, "-c", "print(1)"],
                    "operations": [{"name": "ping", "command": [sys.executable, "-c", "print(1)"]}],
                },
                "mcp": {"server_id": "lazy-mcp"},
            }
        )
        assert cfg is not None
        ctx = AdapterContext(
            module_id="lazy-comp",
            config=cfg,
            data_root=None,
            install_root=None,
            store=None,
            mcp_bridge=None,
        )
        adapter = CompositeAdapter(ctx)
        # Make CLI report READY without install root (binary/none).
        for child in adapter._children:
            if isinstance(child, CliAdapter):
                child._state = ExternalRuntimeState.READY
                child.ensure_ready = lambda: {"ready": True, "install_root": None}  # type: ignore[method-assign]
            if isinstance(child, McpAdapter):
                child._state = ExternalRuntimeState.DISCOVERED

        health = adapter.health()
        self.assertEqual(health.status, ModuleStatus.READY)
        roles = (health.telemetry or {}).get("child_roles") or []
        self.assertTrue(any(r.get("adapter") == "McpAdapter" and r.get("role") == "optional" for r in roles))

    def test_skill_pack_discovered_health_not_error(self) -> None:
        cfg = parse_external_config(
            {
                "adapter": "SKILL_PACK",
                "source_type": "path",
                "path": str(FIXTURES / "fake_skill"),
                "install": {"strategy": "NONE"},
                "skill_roots": ["skills"],
            }
        )
        assert cfg is not None
        ctx = AdapterContext(
            module_id="skill-only",
            config=cfg,
            data_root=None,
            install_root=None,
            store=None,
            mcp_bridge=None,
        )
        skill = SkillPackAdapter(ctx)
        self.assertEqual(skill._state, ExternalRuntimeState.DISCOVERED)
        health = skill.health()
        self.assertEqual(health.status, ModuleStatus.DISCOVERED)
        self.assertNotEqual(health.status, ModuleStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
