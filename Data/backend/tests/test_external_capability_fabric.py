"""Tests for the generic external capability fabric."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from Data.modules.execution.catalog import CapabilityCatalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.execution.types import CapabilityDefinition, CapabilityProviderKind, CapabilityRequest
from Data.modules.function_runtime.types import SideEffect
from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleStatus
from Data.modules.module_manager.discovery import parse_manifest
from Data.modules.module_manager.external.catalog_register import (
    register_external_control_capabilities,
    register_external_module_capabilities,
)
from Data.modules.module_manager.external.executor import ExternalModuleExecutor
from Data.modules.module_manager.external.skills import SkillImporter
from Data.modules.module_manager.external.store import ExternalCapabilityStore
from Data.modules.module_manager.external.types import AdapterType, parse_external_config
from Data.modules.plugins.registry import PluginRegistry


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "external_capabilities"
FACTORY = "Data.modules.module_manager.external.module:create_external_capability_module"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ExternalFabricUnitTests(unittest.TestCase):
    def test_parse_external_config_cli(self) -> None:
        cfg = parse_external_config(
            {
                "adapter": "CLI",
                "source": "https://github.com/example/tool",
                "ref": "main",
                "install": {"strategy": "python_venv"},
                "runtime": {"command": ["python", "tool.py", "{query}"], "timeout_seconds": 30},
                "result": {"format": "json"},
                "assimilation_mode": "EVIDENCE",
            }
        )
        assert cfg is not None
        self.assertEqual(cfg.adapter, AdapterType.CLI)
        self.assertIn("GIT_CHECKOUT", [s.value for s in cfg.install.strategies])

    def test_skill_importer_parses_frontmatter(self) -> None:
        root = FIXTURES / "fake_skill"
        records = SkillImporter().import_tree(root, source_repo="test/fake", module_id="fake-skill")
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[0].name, "demo-scroll")
        self.assertIn("cinematic", (records[0].description or "").lower() + (records[0].trigger_description or "").lower())
        self.assertTrue(records[0].content_hash)

    def test_catalog_source_bounded(self) -> None:
        root = FIXTURES / "fake_catalog"
        records = SkillImporter().import_catalog_index(root, source_repo="test/catalog", module_id="cat")
        self.assertGreaterEqual(len(records), 3)
        self.assertTrue(all(r.catalog_only for r in records))
        self.assertTrue(all(not r.instructions for r in records))

    def test_old_factory_still_works(self) -> None:
        from Data.modules.neuro.echo_module import create_echo_module

        manager = ModuleManager(discovery_roots=(), enabled=True)
        managed = manager.register_instance(create_echo_module(), ready=True)
        self.assertEqual(managed.status, ModuleStatus.READY)
        result = manager.execute("neuro.echo", "ping", {"message": "hi"})
        self.assertEqual(result.status, "COMPLETED")

    def test_manifest_aware_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-cli"
            root.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            manifest = {
                "module_id": "fake-cli",
                "name": "Fake CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool.parent),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "mode": "EPHEMERAL",
                        "command": [sys.executable, str(tool), "{query}"],
                        "timeout_seconds": 30,
                        "operations": [{"name": "search", "command": [sys.executable, str(tool), "{query}"]}],
                    },
                    "result": {"format": "JSON"},
                    "assimilation_mode": "EVIDENCE",
                    "tags": ["test"],
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_cli.search",
                        "name": "Fake Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True, execute_timeout_seconds=60)
            manager.discover()
            manager.initialize(
                "fake-cli",
                ModuleContext(database_path=str(db), data_root=tmp, metadata={}),
            )
            # install/ready
            ready = manager.ensure_ready("fake-cli")
            self.assertTrue(ready.get("ready"))
            result = manager.execute("fake-cli", "search", {"query": "leviathan"})
            self.assertEqual(result.status, "COMPLETED")
            assert result.output is not None
            self.assertIn("parts", result.output)
            self.assertGreaterEqual(len(result.output.get("source_refs") or []), 1)

    def test_process_service_start_stop_health(self) -> None:
        port = _free_port()
        server = FIXTURES / "fake_http_service" / "server.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-svc"
            root.mkdir(parents=True)
            manifest = {
                "module_id": "fake-svc",
                "name": "Fake Service",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "PROCESS_SERVICE",
                    "source_type": "path",
                    "path": str(server.parent),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "mode": "RESIDENT",
                        "command": [sys.executable, str(server), str(port)],
                        "cwd": str(server.parent),
                        "startup_timeout_seconds": 10,
                        "ready_probe": {
                            "kind": "http",
                            "url": f"http://127.0.0.1:{port}/health",
                            "expect_status": 200,
                        },
                        "base_url": f"http://127.0.0.1:{port}",
                        "operations": [
                            {"name": "echo", "method": "POST", "path": "/echo", "body_from": ["message"]},
                        ],
                    },
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_svc.echo",
                        "name": "Echo",
                        "external_name": "echo",
                        "side_effects": ["NETWORK"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-svc", ModuleContext(database_path=str(db), data_root=tmp))
            started = manager.start("fake-svc")
            self.assertEqual(started.get("status"), "RUNNING")
            health = manager.health("fake-svc")
            self.assertIn(health.status.value, {"READY", "RUNNING"})
            result = manager.execute("fake-svc", "echo", {"message": "hi"})
            self.assertEqual(result.status, "COMPLETED")
            manager.stop("fake-svc")
            stopped = manager.get("fake-svc")
            assert stopped is not None
            self.assertEqual(stopped.status, ModuleStatus.STOPPED)

    def test_skill_pack_index_and_on_demand_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-skill"
            root.mkdir(parents=True)
            skill_src = FIXTURES / "fake_skill"
            manifest = {
                "module_id": "fake-skill",
                "name": "Fake Skill Pack",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "SKILL_PACK",
                    "source_type": "path",
                    "path": str(skill_src),
                    "install": {"strategy": "NONE"},
                    "skill_roots": ["skills"],
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_skill.search",
                        "name": "Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    },
                    {
                        "capability_id": "external.fake_skill.load",
                        "name": "Load",
                        "external_name": "load",
                        "side_effects": ["READ"],
                    },
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-skill", ModuleContext(database_path=str(db), data_root=tmp))
            manager.ensure_installed("fake-skill")
            listed = manager.execute("fake-skill", "search", {"query": "cinematic"})
            self.assertEqual(listed.status, "COMPLETED")
            skills = (listed.output or {}).get("structured_data", {}).get("skills") or []
            self.assertGreaterEqual(len(skills), 1)
            loaded = manager.execute("fake-skill", "load", {"name": "demo-scroll"})
            self.assertEqual(loaded.status, "COMPLETED")
            instructions = (loaded.output or {}).get("structured_data", {}).get("instructions") or ""
            self.assertIn("cinematic", instructions.lower())

    def test_store_persistence_and_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalCapabilityStore(Path(tmp) / "c.db")
            store.initialize()
            store.upsert_module(
                module_id="m1",
                name="M1",
                adapter="CLI",
                runtime_state="RUNNING",
                desired_state="RUNNING",
            )
            store.upsert_process(
                module_id="m1",
                pid=999999,
                fingerprint="bogus",
                command=["false"],
                health="OK",
            )
            row = store.get_module("m1")
            assert row is not None
            self.assertEqual(row["runtime_state"], "RUNNING")
            self.assertTrue(row["truth"]["persisted_runtime_state_is_not_live_health"])

    def test_gateway_module_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-cli"
            root.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            manifest = {
                "module_id": "fake-cli",
                "name": "Fake CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool.parent),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "command": [sys.executable, str(tool), "{query}"],
                        "operations": [{"name": "search", "command": [sys.executable, str(tool), "{query}"]}],
                    },
                    "result": {"format": "JSON"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_cli.search",
                        "name": "Fake Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-cli", ModuleContext(database_path=str(db), data_root=tmp))
            catalog = CapabilityCatalog()
            register_external_control_capabilities(catalog)
            plugins = PluginRegistry(catalog)
            managed = manager.get("fake-cli")
            assert managed is not None
            register_external_module_capabilities(catalog=catalog, plugin_registry=plugins, managed=managed)
            gateway = ExecutionGateway(catalog=catalog, module_executor=ExternalModuleExecutor(manager))
            result = gateway.execute(
                CapabilityRequest(
                    capability_id="external.fake_cli.search",
                    arguments={"query": "x"},
                    requested_by="test",
                )
            )
            self.assertEqual(result.status.value, "COMPLETED")
            self.assertIn("parts", result.output or {})

    def test_declared_source_manifests_parse(self) -> None:
        # Resolve from this test file — never hardcode /workspace (absent on CI runners).
        root = Path(__file__).resolve().parents[2] / "external_capabilities"
        self.assertTrue(root.is_dir(), f"missing external_capabilities at {root}")
        manifests = sorted(root.glob("*/module.json"))
        self.assertGreaterEqual(len(manifests), 20)
        for path in manifests:
            data = json.loads(path.read_text(encoding="utf-8"))
            parsed = parse_manifest(data, source_path=path)
            self.assertTrue(parsed.module_id)
            self.assertIn("external", parsed.metadata)
            cfg = parse_external_config(parsed.metadata["external"])
            self.assertIsNotNone(cfg)

    def test_cancellation_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "slow"
            root.mkdir(parents=True)
            # Slow command
            slow = Path(tmp) / "slow.py"
            slow.write_text("import time\ntime.sleep(30)\nprint('late')\n", encoding="utf-8")
            manifest = {
                "module_id": "slow",
                "name": "Slow",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "command": [sys.executable, str(slow)],
                        "timeout_seconds": 60,
                        "operations": [{"name": "run", "command": [sys.executable, str(slow)]}],
                    },
                },
                "capabilities": [
                    {"capability_id": "external.slow.run", "name": "Run", "external_name": "run", "side_effects": ["EXECUTE"]}
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True, execute_timeout_seconds=60)
            manager.discover()
            manager.initialize("slow", ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp))
            cancel = {"flag": False}

            def _cancel() -> bool:
                return cancel["flag"]

            # Invoke via adapter directly for cancel_check support
            inst = manager.get("slow").instance  # type: ignore[union-attr]
            assert inst is not None
            adapter = inst._adapter  # type: ignore[attr-defined]

            def _run() -> None:
                time.sleep(0.2)
                cancel["flag"] = True

            threading.Thread(target=_run, daemon=True).start()
            result = adapter.invoke("run", {}, cancel_check=_cancel)
            self.assertEqual(result.status, "CANCELLED")


class ExternalAdapterFixtureE2ETests(unittest.TestCase):
    """Fixture e2e for adapter kinds that must not depend on live third-party networks."""

    def test_http_openapi_operations(self) -> None:
        port = _free_port()
        server = FIXTURES / "fake_http_service" / "server.py"
        proc = subprocess.Popen(
            [sys.executable, str(server), str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "fake-http"
                root.mkdir(parents=True)
                manifest = {
                    "module_id": "fake-http",
                    "name": "Fake HTTP",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "HTTP_OPENAPI",
                        "source_type": "none",
                        "install": {"strategy": "NONE"},
                        "runtime": {
                            "base_url": f"http://127.0.0.1:{port}",
                            "health_probe": {
                                "kind": "http",
                                "url": f"http://127.0.0.1:{port}/health",
                                "expect_status": 200,
                            },
                            "operations": [
                                {
                                    "name": "echo",
                                    "method": "POST",
                                    "path": "/echo",
                                    "body": "json",
                                }
                            ],
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.fake_http.echo",
                            "name": "Echo",
                            "external_name": "echo",
                            "side_effects": ["NETWORK"],
                        }
                    ],
                }
                (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
                manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
                manager.discover()
                manager.initialize(
                    "fake-http",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                ready = manager.ensure_ready("fake-http")
                self.assertTrue(ready.get("ready") or ready.get("status") in {"READY", "COMPLETED"})
                result = manager.execute("fake-http", "echo", {"message": "hi"})
                self.assertEqual(result.status, "COMPLETED")
                structured = (result.output or {}).get("structured_data") or {}
                self.assertTrue(structured.get("ok") or "echo" in structured or "parts" in (result.output or {}))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                proc.kill()

    def test_script_package_runs(self) -> None:
        script = FIXTURES / "fake_script" / "run.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-script"
            root.mkdir(parents=True)
            # Make a local copy executable via python for cross-platform CI.
            runner = Path(tmp) / "run.py"
            runner.write_text(
                "import json\nprint(json.dumps({'summary':'script ok','files':['out.txt']}))\n"
                "open('out.txt','w').write('hello')\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "fake-script",
                "name": "Fake Script",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "SCRIPT_PACKAGE",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "command": [sys.executable, str(runner)],
                        "cwd": str(tmp),
                        "operations": [
                            {"name": "build", "command": [sys.executable, str(runner)]}
                        ],
                    },
                    "result": {"format": "json", "artifact_globs": ["out.txt"]},
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_script.build",
                        "name": "Build",
                        "external_name": "build",
                        "side_effects": ["EXECUTE"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-script",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            result = manager.execute("fake-script", "build", {})
            self.assertEqual(result.status, "COMPLETED")
            self.assertTrue(script.exists())  # fixture present even if unused directly

    def test_composite_skill_plus_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-composite"
            root.mkdir(parents=True)
            skill_src = FIXTURES / "fake_skill"
            tool = FIXTURES / "fake_cli" / "tool.py"
            # Copy skill tree into module root for SKILL_PACK child.
            import shutil

            shutil.copytree(skill_src, root / "skills_src")
            manifest = {
                "module_id": "fake-composite",
                "name": "Fake Composite",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "COMPOSITE",
                    "source_type": "path",
                    "path": str(root / "skills_src"),
                    "install": {"strategy": "NONE"},
                    "children": ["SKILL_PACK", "CLI"],
                    "skill_roots": ["skills"],
                    "runtime": {
                        "command": [sys.executable, str(tool), "{query}"],
                        "operations": [
                            {
                                "name": "search",
                                "command": [sys.executable, str(tool), "{query}"],
                            }
                        ],
                    },
                    "result": {"format": "json"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_composite.search",
                        "name": "Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    },
                    {
                        "capability_id": "external.fake_composite.load",
                        "name": "Load skill",
                        "external_name": "load",
                        "side_effects": ["READ"],
                    },
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-composite",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("fake-composite")
            listed = manager.execute("fake-composite", "search", {"query": "cinematic"})
            self.assertEqual(listed.status, "COMPLETED")

    def test_catalog_materialize_enables_local_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-cat"
            root.mkdir(parents=True)
            import shutil

            cat = FIXTURES / "fake_catalog"
            shutil.copytree(cat, root / "catalog")
            # Also drop a real SKILL.md so materialize can import instructions.
            skill_dir = root / "catalog" / "skills" / "demo"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: demo-materialize\ndescription: materialize me\n---\n# Demo\nDo the thing.\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "fake-cat",
                "name": "Fake Catalog",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CATALOG_SOURCE",
                    "source_type": "path",
                    "path": str(root / "catalog"),
                    "install": {"strategy": "NONE"},
                    "skill_roots": ["."],
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_cat.search",
                        "name": "Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    },
                    {
                        "capability_id": "external.fake_cat.materialize",
                        "name": "Materialize",
                        "external_name": "materialize",
                        "side_effects": ["WRITE"],
                    },
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "c.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-cat", ModuleContext(database_path=str(db), data_root=tmp))
            manager.ensure_installed("fake-cat")
            manager.execute("fake-cat", "refresh", {})
            search = manager.execute("fake-cat", "search", {"query": "demo", "limit": 10})
            self.assertEqual(search.status, "COMPLETED")
            skills = (search.output or {}).get("structured_data", {}).get("skills") or []
            self.assertGreaterEqual(len(skills), 1)
            target = skills[0].get("skill_id") or skills[0].get("name")
            mat = manager.execute("fake-cat", "materialize", {"skill_id": target})
            self.assertEqual(mat.status, "COMPLETED")

    def test_mcp_adapter_lifecycle_via_fake_bridge(self) -> None:
        """McpAdapter start/status/stop through a real McpBridge + fake stdio server."""
        from Data.modules.mcp import McpBridge, McpStore
        from Data.modules.mcp.limits import McpLimits

        fake = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
        self.assertTrue(fake.exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-mcp"
            root.mkdir(parents=True)
            # Local path install of a stub package directory (no network).
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "README.md").write_text("fake mcp pkg\n", encoding="utf-8")
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            store = McpStore(Path(tmp) / "mcp.db")
            store.initialize()
            bridge = McpBridge(
                store=store,
                catalog=catalog,
                plugin_registry=plugins,
                enabled=True,
                stdio_enabled=True,
                http_enabled=False,
                auto_expand_modules=False,
                allow_outbound=False,
                limits=McpLimits(startup_timeout_seconds=10.0, max_restart_attempts=1),
            )
            bridge.initialize()
            cfg = bridge.register_server(
                display_name="Fake MCP",
                transport="stdio",
                source_kind="manual",
                source_key="fake-mcp",
                server_id="fake-mcp",
                command=sys.executable,
                args=[str(fake), "--mode=normal"],
                enabled=True,
                trust="untrusted",
                expand_tools=True,
            )
            self.assertEqual(cfg.server_id, "fake-mcp")
            manifest = {
                "module_id": "fake-mcp",
                "name": "Fake MCP Module",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "MCP",
                    "source_type": "path",
                    "path": str(pkg),
                    "install": {"strategy": "NONE"},
                    "runtime": {"mode": "LAZY", "mcp_server_id": "fake-mcp", "eager_start": False},
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_mcp.start",
                        "name": "Start",
                        "external_name": "start",
                        "side_effects": ["EXECUTE"],
                    },
                    {
                        "capability_id": "external.fake_mcp.status",
                        "name": "Status",
                        "external_name": "status",
                        "side_effects": ["READ"],
                    },
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-mcp",
                ModuleContext(
                    database_path=str(Path(tmp) / "c.db"),
                    data_root=tmp,
                    metadata={"mcp_bridge": bridge},
                ),
            )
            started = manager.execute("fake-mcp", "start", {})
            self.assertEqual(started.status, "COMPLETED")
            status = manager.execute("fake-mcp", "status", {})
            self.assertEqual(status.status, "COMPLETED")
            stopped = manager.execute("fake-mcp", "stop", {})
            self.assertEqual(stopped.status, "COMPLETED")

    def test_assimilation_idempotency_skips_duplicate(self) -> None:
        from Data.modules.module_manager.external.post_result import (
            queue_or_run_assimilation,
            resolve_assimilation_mode,
        )
        from Data.modules.module_manager.external.types import AssimilationMode

        class _Svc:
            def __init__(self) -> None:
                self.calls = 0

            def assimilate_external_capability(self, **kwargs):  # noqa: ANN003
                self.calls += 1

                class R:
                    receipt_id = "r1"
                    ok = True

                    def public_dict(self):
                        return {"receipt_id": self.receipt_id, "ok": True}

                return R()

        svc = _Svc()
        mode = AssimilationMode.KNOWLEDGE_CANDIDATE
        first = queue_or_run_assimilation(
            mode=mode,
            capability_id="external.fake.search",
            module_id="fake",
            request_id="same-req",
            run_id=None,
            job_id=None,
            output={"summary": "hello world evidence"},
            status="COMPLETED",
            assimilation_service=svc,
        )
        second = queue_or_run_assimilation(
            mode=mode,
            capability_id="external.fake.search",
            module_id="fake",
            request_id="same-req",
            run_id=None,
            job_id=None,
            output={"summary": "hello world evidence"},
            status="COMPLETED",
            assimilation_service=svc,
        )
        self.assertTrue(first.get("completed") or first.get("queued") is False)
        self.assertEqual(svc.calls, 1)
        self.assertEqual(second.get("reason"), "duplicate_skipped")

    def test_skill_shortlist_includes_skill_ids(self) -> None:
        # Load broker module without pulling cognition package __init__ (heavy deps).
        import importlib.util
        import sys

        broker_path = (
            Path(__file__).resolve().parents[2]
            / "modules"
            / "cognition"
            / "capability_broker.py"
        )
        name = "lev_cap_broker_under_test"
        spec = importlib.util.spec_from_file_location(name, broker_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        CapabilityBroker = mod.CapabilityBroker

        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalCapabilityStore(Path(tmp) / "c.db")
            store.initialize()
            store.upsert_skill(
                {
                    "skill_id": "scroll-demo",
                    "name": "demo-scroll",
                    "description": "Build a cinematic scrolling website",
                    "source_repo": "test/fake",
                    "content_hash": "abc",
                    "enabled": True,
                    "catalog_only": False,
                    "trigger_description": "cinematic scroll website",
                }
            )
            broker = CapabilityBroker(catalog=CapabilityCatalog())
            short = broker.shortlist_for_task(
                goal="Build a cinematic scrolling website",
                skill_store=store,
                limit=6,
            )
            self.assertTrue(any(str(cid).startswith("skill:") for cid in short.capability_ids))
            self.assertIn("skill:scroll-demo", short.inspected)


class ExternalAcceptanceMatrixTests(unittest.TestCase):
    def test_matrix_file_exists_and_covers_sources(self) -> None:
        matrix = Path(__file__).resolve().parent / "external_sources_acceptance_matrix.json"
        self.assertTrue(matrix.exists(), f"missing acceptance matrix at {matrix}")
        data = json.loads(matrix.read_text(encoding="utf-8"))
        sources = {row["source"] for row in data["sources"]}
        required = {
            "Datalux/Osintgram",
            "wonderwhy-er/DesktopCommanderMCP",
            "elementalsouls/Claude-OSINT",
            "Panniantong/Agent-Reach",
            "HunxByts/GhostTrack",
            "HKUDS/Vibe-Trading",
            "anthropics/financial-services",
            "jason8745/llm-agent-trader",
            "Fincept-Corporation/FinceptTerminal",
            "singhharsh1708/scrollcraft",
            "ukanwat/selfstarter",
            "THU-MAIC/OpenMAIC",
            "Companion-Inc/feynman",
            "multica-ai/andrej-karpathy-skills",
            "DietrichGebert/ponytail",
            "anthropics/skills",
            "mattpocock/skills",
            "obra/superpowers",
            "cloudflare/security-audit-skill",
            "tech-leads-club/agent-skills",
            "VoltAgent/awesome-openclaw-skills",
        }
        self.assertTrue(required.issubset(sources))
        for row in data["sources"]:
            self.assertIn(row["status"], {"PASS", "PARTIAL", "BLOCKED_EXTERNAL", "NOT_APPLICABLE", "FAILED"})


class ExternalAssimilationAndScaleTests(unittest.TestCase):
    def test_assimilate_external_capability_writes_knowledge_with_provenance(self) -> None:
        from Data.modules.intelligence.assimilation import KnowledgeAssimilationService
        from Data.modules.knowledge.store import KnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            kdb = Path(tmp) / "knowledge.db"
            cdb = Path(tmp) / "control.db"
            knowledge = KnowledgeStore(kdb)
            knowledge.initialize()
            service = KnowledgeAssimilationService(
                database_path=cdb,
                knowledge_store=knowledge,
            )
            receipt = service.assimilate_external_capability(
                mode="KNOWLEDGE_CANDIDATE",
                capability_id="external.fake.search",
                module_id="fake-cli",
                request_id="req-1",
                run_id="run-1",
                output={
                    "summary": "Found 3 discussions about widgets",
                    "source_refs": ["https://example.com/a", "https://example.com/b"],
                    "artifact_refs": ["artifact:report-1"],
                    "structured_data": {"items": [{"title": "A"}, {"title": "B"}, {"title": "C"}]},
                },
                retrieved_at="2026-09-27T12:00:00+00:00",
            )
            self.assertTrue(receipt.ok)
            self.assertEqual(receipt.success_count, 1)
            self.assertEqual(receipt.metadata.get("retrieved_at"), "2026-09-27T12:00:00+00:00")
            hits = knowledge.search_lexical("widgets", limit=5)
            self.assertGreaterEqual(len(hits), 1)

            # Idempotent document id — second assimilate same request replaces, not duplicates forever.
            receipt2 = service.assimilate_external_capability(
                mode="KNOWLEDGE_CANDIDATE",
                capability_id="external.fake.search",
                module_id="fake-cli",
                request_id="req-1",
                output={"summary": "Found 3 discussions about widgets"},
            )
            self.assertTrue(receipt2.ok)
            self.assertEqual(receipt.document_ids, receipt2.document_ids)

    def test_post_result_none_mode_skips(self) -> None:
        from Data.modules.module_manager.external.post_result import (
            queue_or_run_assimilation,
            resolve_assimilation_mode,
        )
        from Data.modules.module_manager.external.types import AssimilationMode

        mode = resolve_assimilation_mode({"assimilation_mode": "NONE"}, {})
        self.assertEqual(mode, AssimilationMode.NONE)
        out = queue_or_run_assimilation(
            mode=mode,
            capability_id="x",
            module_id="m",
            request_id="r",
            run_id=None,
            job_id=None,
            output={"summary": "hi"},
            status="COMPLETED",
        )
        self.assertFalse(out["queued"])
        self.assertEqual(out["reason"], "skipped")

    def test_catalog_scale_bounded_search_does_not_load_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalCapabilityStore(Path(tmp) / "c.db")
            store.initialize()
            # Simulate hundreds of catalog entries without reading bodies.
            for i in range(250):
                store.upsert_skill(
                    {
                        "skill_id": f"cat-{i}",
                        "name": f"skill-{i}",
                        "description": f"catalog entry {i} for widgets",
                        "source_repo": "VoltAgent/awesome-openclaw-skills",
                        "catalog_only": True,
                        "enabled": True,
                        "content_hash": f"hash-{i}",
                    }
                )
            t0 = time.perf_counter()
            rows = store.search_skills(
                query="widgets",
                include_catalog=True,
                enabled_only=True,
                limit=25,
                offset=0,
            )
            elapsed = time.perf_counter() - t0
            self.assertEqual(len(rows), 25)
            self.assertTrue(all(r.get("catalog_only") for r in rows))
            # Catalog search returns metadata only — no instruction bodies in rows.
            self.assertTrue(all("instruction_artifact" in r for r in rows))
            self.assertLess(elapsed, 2.0)
            self.assertEqual(store.count_skills(catalog_only=True), 250)

    def test_plugin_registry_hydrate_enabled_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalCapabilityStore(Path(tmp) / "c.db")
            store.initialize()
            store.upsert_plugin_binding(
                {
                    "plugin_id": "ext.demo",
                    "name": "Demo",
                    "kind": "DECLARATIVE",
                    "status": "ENABLED",
                    "bindings": [{"capability_id": "external.demo.op", "external_name": "op"}],
                }
            )
            catalog = CapabilityCatalog()
            catalog.register(
                CapabilityDefinition(
                    id="external.demo.op",
                    name="Demo Op",
                    description="demo",
                    provider_kind=CapabilityProviderKind.EXTERNAL,
                    provider_ref="demo",
                    side_effects=(SideEffect.READ,),
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            )
            registry = PluginRegistry(catalog)
            registry.attach_store(store)
            n = registry.hydrate_from_store()
            self.assertGreaterEqual(n, 1)
            bindings = store.list_plugin_bindings()
            self.assertEqual(len(bindings), 1)
            self.assertEqual(bindings[0]["status"], "ENABLED")
            self.assertTrue(bindings[0]["truth"]["persisted_enabled_is_not_runtime_ready"])
            hydrated = next(p for p in registry.list() if p.plugin_id == "ext.demo")
            self.assertTrue(hydrated.metadata.get("persisted_enabled_is_not_runtime_ready"))
            # ENABLED config != runtime READY.
            self.assertNotEqual(str(hydrated.status), "READY")

    def test_executor_records_observation(self) -> None:
        from Data.modules.observations import ObservationStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-cli"
            root.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            manifest = {
                "module_id": "fake-cli",
                "name": "Fake CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool.parent),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "command": [sys.executable, str(tool), "{query}"],
                        "operations": [
                            {"name": "search", "command": [sys.executable, str(tool), "{query}"]}
                        ],
                    },
                    "result": {"format": "json"},
                    "assimilation_mode": "NONE",
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_cli.search",
                        "name": "Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-cli", ModuleContext(database_path=str(db), data_root=tmp))
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            managed = manager.get("fake-cli")
            assert managed is not None
            register_external_module_capabilities(
                catalog=catalog, plugin_registry=plugins, managed=managed
            )
            obs = ObservationStore(db)
            obs.initialize()
            gateway = ExecutionGateway(catalog=catalog)
            gateway.module_executor = ExternalModuleExecutor(
                manager,
                observation_store=obs,
                catalog=catalog,
            )
            result = gateway.execute(
                CapabilityRequest(
                    capability_id="external.fake_cli.search",
                    arguments={"query": "hello"},
                    request_id="obs-req-1",
                )
            )
            self.assertEqual(result.status.value, "COMPLETED")
            obs_id = (result.telemetry or {}).get("observation_id") or (
                (result.output or {}).get("metadata") or {}
            ).get("observation_id")
            self.assertTrue(obs_id)

    def test_restart_reconciles_fake_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-cli"
            root.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            manifest = {
                "module_id": "fake-cli",
                "name": "Fake CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tool.parent),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "command": [sys.executable, str(tool), "{query}"],
                        "operations": [
                            {"name": "search", "command": [sys.executable, str(tool), "{query}"]}
                        ],
                    },
                    "result": {"format": "json"},
                },
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            store = ExternalCapabilityStore(db)
            store.initialize()
            store.upsert_module(
                module_id="fake-cli",
                name="Fake CLI",
                adapter="CLI",
                runtime_state="RUNNING",
                desired_state="READY",
            )
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-cli",
                ModuleContext(
                    database_path=str(db),
                    data_root=tmp,
                    metadata={"external_capability_store": store},
                ),
            )
            # After init/reconcile, persisted RUNNING without a live process must not stay RUNNING.
            row = store.get_module("fake-cli")
            assert row is not None
            self.assertNotEqual(row["runtime_state"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
