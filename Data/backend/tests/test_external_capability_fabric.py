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
from typing import Any

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

    def test_shipped_manifests_parse_after_live_audit(self) -> None:
        root = Path(__file__).resolve().parents[2] / "external_capabilities"
        required = {
            "feynman": AdapterType.COMPOSITE,
            "openmaic": AdapterType.COMPOSITE,
            "selfstarter": AdapterType.COMPOSITE,
            "scrollcraft": AdapterType.COMPOSITE,
            "fincept-terminal": AdapterType.COMPOSITE,
            "agent-reach": AdapterType.COMPOSITE,
            "osintgram": AdapterType.COMPOSITE,
            "llm-agent-trader": AdapterType.COMPOSITE,
            "financial-services": AdapterType.SKILL_PACK,
            "desktop-commander-mcp": AdapterType.MCP,
            "awesome-openclaw-skills": AdapterType.CATALOG_SOURCE,
        }
        for module_id, adapter in required.items():
            manifest = json.loads((root / module_id / "module.json").read_text(encoding="utf-8"))
            cfg = parse_external_config(manifest.get("external"))
            assert cfg is not None, module_id
            self.assertEqual(cfg.adapter, adapter, module_id)
            self.assertTrue(manifest.get("capabilities"), module_id)
        feynman = json.loads((root / "feynman" / "module.json").read_text(encoding="utf-8"))
        self.assertIn("NODE_NPM", json.dumps(feynman["external"]["install"]))
        self.assertNotIn("python -m feynman", json.dumps(feynman))
        openmaic = json.loads((root / "openmaic" / "module.json").read_text(encoding="utf-8"))
        self.assertIn("3000", json.dumps(openmaic["external"]["runtime"]))
        self.assertIn("NODE_PNPM", json.dumps(openmaic["external"]["install"]))
        self.assertIn("/api/health", json.dumps(openmaic["external"]["runtime"]))
        self.assertIn("/api/generate-classroom", json.dumps(openmaic["external"]["runtime"]))
        self.assertIn("body_aliases", json.dumps(openmaic["external"]["runtime"]))
        scroll = json.loads((root / "scrollcraft" / "module.json").read_text(encoding="utf-8"))
        self.assertIn("plugins/scrollcraft/skills", json.dumps(scroll["external"]))

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

    def test_gateway_cancel_and_progress_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "slow"
            root.mkdir(parents=True)
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
                    {
                        "capability_id": "external.slow.run",
                        "name": "Run",
                        "external_name": "run",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("slow", ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp))
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            managed = manager.get("slow")
            assert managed is not None
            register_external_module_capabilities(
                catalog=catalog, plugin_registry=plugins, managed=managed
            )
            gateway = ExecutionGateway(catalog=catalog)
            gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
            events: list[tuple[float, str, str]] = []
            cancel = {"flag": False}

            def _progress(pct: float, phase: str, msg: str) -> None:
                events.append((float(pct), str(phase), str(msg)))
                if len(events) >= 2:
                    cancel["flag"] = True

            result = gateway.execute(
                CapabilityRequest(
                    capability_id="external.slow.run",
                    arguments={
                        "_progress_cb": _progress,
                        "_cancel_check": lambda: cancel["flag"],
                    },
                    request_id="gw-cancel-1",
                )
            )
            self.assertEqual(
                result.status.value,
                "CANCELLED",
                msg=f"unexpected status={result.status.value} error={result.error} events={events}",
            )
            self.assertGreaterEqual(len(events), 1)
            self.assertTrue(any(e[1] in {"starting", "running", "cancelled"} for e in events))

    def test_source_freshness_fields_preserved(self) -> None:
        from Data.modules.module_manager.external.post_result import queue_or_run_assimilation
        from Data.modules.module_manager.external.results import normalize_osint_items
        from Data.modules.module_manager.external.types import AssimilationMode

        items = normalize_osint_items(
            [
                {
                    "title": "News",
                    "url": "https://example.com/n",
                    "published_at": "2026-01-02T00:00:00+00:00",
                    "available_at": "2026-01-02T01:00:00+00:00",
                }
            ],
            query="x",
            provider="agent-reach",
            retrieved_at="2026-09-27T12:00:00+00:00",
        )
        self.assertEqual(items[0]["published_at"], "2026-01-02T00:00:00+00:00")
        self.assertEqual(items[0]["available_at"], "2026-01-02T01:00:00+00:00")
        self.assertEqual(items[0]["retrieved_at"], "2026-09-27T12:00:00+00:00")
        self.assertNotEqual(items[0]["published_at"], items[0]["retrieved_at"])

        assim = queue_or_run_assimilation(
            mode=AssimilationMode.EVIDENCE,
            capability_id="external.agent_reach.search",
            module_id="agent-reach",
            request_id="fresh-1",
            run_id=None,
            job_id=None,
            output={
                "summary": "news",
                "source_refs": items,
                "metadata": {"retrieved_at": "2026-09-27T12:00:00+00:00"},
            },
            status="COMPLETED",
        )
        self.assertTrue(assim.get("completed") or assim.get("queued") is False)
        # Evidence path must not collapse published time into timeless memory.
        self.assertEqual(items[0]["published_at"], "2026-01-02T00:00:00+00:00")


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
                                },
                                {
                                    "name": "echo_alias",
                                    "method": "POST",
                                    "path": "/echo",
                                    "body_from": ["topic", "message"],
                                    "body_aliases": {"topic": "message"},
                                },
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
                aliased = manager.execute("fake-http", "echo_alias", {"topic": "aliased-hi"})
                self.assertEqual(aliased.status, "COMPLETED")
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
            # Thousands of catalog entries — metadata only, never prompt-injected.
            n = 3000
            for i in range(n):
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
            self.assertTrue(all(not (r.get("instructions") or "") for r in rows))
            self.assertLess(elapsed, 3.0)
            self.assertEqual(store.count_skills(catalog_only=True), n)
            page2 = store.search_skills(query="widgets", include_catalog=True, limit=25, offset=25)
            self.assertEqual(len(page2), 25)
            self.assertNotEqual(rows[0]["skill_id"], page2[0]["skill_id"])

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

    def test_version_update_activate_rollback(self) -> None:
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
                    "ref": "v1",
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
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-cli", ModuleContext(database_path=str(db), data_root=tmp))
            v1 = manager.install_version("fake-cli", ref="v1", activate=True)
            self.assertTrue(v1.get("version_id"))
            v2 = manager.install_version("fake-cli", ref="v2", activate=False)
            self.assertNotEqual(v1["version_id"], v2["version_id"])
            check = manager.check_update("fake-cli")
            self.assertIn("update_available", check)
            # Active job blocks activation.
            manager.register_job("fake-cli", "job-busy")
            with self.assertRaises(Exception):
                manager.activate_version("fake-cli", v2["version_id"])
            manager.unregister_job("fake-cli", "job-busy")
            activated = manager.activate_version("fake-cli", v2["version_id"])
            self.assertEqual(activated["version_id"], v2["version_id"])
            rolled = manager.rollback_version("fake-cli", version_id=v1["version_id"])
            self.assertEqual(rolled["version_id"], v1["version_id"])
            versions = manager.list_versions("fake-cli")
            self.assertGreaterEqual(len(versions), 2)

    def test_trading_boundary_rejects_mutation(self) -> None:
        from Data.modules.module_manager.external.trading_boundary import (
            enforce_trading_boundary,
            looks_like_trading_mutation,
        )

        self.assertTrue(looks_like_trading_mutation("place_order", {"symbol": "AAPL", "side": "BUY", "quantity": 1}))
        self.assertFalse(looks_like_trading_mutation("analyze_factor", {"symbol": "AAPL"}))
        rejected = enforce_trading_boundary(
            flags={"marketsim_bypass_forbidden": True, "real_money_blocked": True},
            capability_id="external.vibe_trading.place_order",
            operation="place_order",
            arguments={"symbol": "NVDA", "side": "BUY", "quantity": 10},
            request_id="tb-1",
        )
        assert rejected is not None
        self.assertEqual(rejected.status.value, "REJECTED")
        self.assertIn("TRADING_BOUNDARY", rejected.error or "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-finance"
            root.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            manifest = {
                "module_id": "fake-finance",
                "name": "Fake Finance",
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
                            {
                                "name": "place_order",
                                "command": [sys.executable, str(tool), "{query}"],
                            },
                            {
                                "name": "analyze",
                                "command": [sys.executable, str(tool), "{query}"],
                            },
                        ],
                    },
                    "result": {"format": "json"},
                    "domain": "finance",
                    "metadata": {
                        "marketsim_bypass_forbidden": True,
                        "real_money_blocked": True,
                    },
                },
                "capabilities": [
                    {
                        "capability_id": "external.fake_finance.place_order",
                        "name": "Place Order",
                        "external_name": "place_order",
                        "side_effects": ["READ"],
                    },
                    {
                        "capability_id": "external.fake_finance.analyze",
                        "name": "Analyze",
                        "external_name": "analyze",
                        "side_effects": ["READ"],
                    },
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-finance", ModuleContext(database_path=str(db), data_root=tmp))
            manager.ensure_installed("fake-finance")
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            managed = manager.get("fake-finance")
            assert managed is not None
            register_external_module_capabilities(
                catalog=catalog, plugin_registry=plugins, managed=managed
            )
            gateway = ExecutionGateway(catalog=catalog)
            gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
            blocked = gateway.execute(
                CapabilityRequest(
                    capability_id="external.fake_finance.place_order",
                    arguments={"symbol": "AAPL", "side": "BUY", "quantity": 1},
                    request_id="tb-gw-1",
                )
            )
            self.assertEqual(blocked.status.value, "REJECTED")
            ok = gateway.execute(
                CapabilityRequest(
                    capability_id="external.fake_finance.analyze",
                    arguments={"query": "momentum"},
                    request_id="tb-gw-2",
                )
            )
            self.assertEqual(ok.status.value, "COMPLETED")
            meta = (ok.output or {}).get("metadata") or {}
            self.assertFalse(meta.get("marketsim_authority", True))

    def test_idle_shutdown_process_service(self) -> None:
        from datetime import datetime, timedelta, timezone

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
                        "mode": "LAZY",
                        "command": [sys.executable, str(server), str(port)],
                        "cwd": str(server.parent),
                        "idle_timeout_seconds": 0.2,
                        "startup_timeout_seconds": 10,
                        "ready_probe": {
                            "kind": "http",
                            "url": f"http://127.0.0.1:{port}/health",
                            "expect_status": 200,
                        },
                        "base_url": f"http://127.0.0.1:{port}",
                    },
                },
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            db = Path(tmp) / "control.db"
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("fake-svc", ModuleContext(database_path=str(db), data_root=tmp))
            started = manager.start("fake-svc")
            self.assertEqual(started.get("status"), "RUNNING")
            managed = manager.get("fake-svc")
            assert managed is not None and managed.instance is not None
            adapter = managed.instance._adapter
            adapter._last_used_at = datetime.now(timezone.utc) - timedelta(seconds=5)
            if managed.instance._store is not None:
                with managed.instance._store.connect() as conn:
                    conn.execute(
                        "UPDATE external_modules SET last_used_at = ? WHERE module_id = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), "fake-svc"),
                    )
            stopped = manager.sweep_idle_modules()
            self.assertTrue(any(s.get("module_id") == "fake-svc" for s in stopped))
            # Active jobs must block idle shutdown.
            manager.start("fake-svc")
            adapter = manager.get("fake-svc").instance._adapter  # type: ignore[union-attr]
            adapter._last_used_at = datetime.now(timezone.utc) - timedelta(seconds=5)
            manager.register_job("fake-svc", "keep-alive")
            blocked = manager.sweep_idle_modules()
            self.assertFalse(any(s.get("module_id") == "fake-svc" for s in blocked))
            manager.unregister_job("fake-svc", "keep-alive")
            manager.stop("fake-svc")

    def test_missing_binaries_python_alias(self) -> None:
        from Data.modules.module_manager.external.install import _missing_binaries

        # Environments often ship only python3 — "python" must still resolve.
        self.assertEqual(_missing_binaries(("python", "python3")), [])
        missing = _missing_binaries(("definitely-not-a-real-binary-xyz",))
        self.assertEqual(missing, ["definitely-not-a-real-binary-xyz"])

    def test_add_version_auto_upserts_module_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "control.db"
            store = ExternalCapabilityStore(db)
            store.initialize()
            store.add_version(
                version_id="mod-a:v1",
                module_id="mod-a",
                install_root=str(Path(tmp) / "root"),
                activate=True,
                adapter="SKILL_PACK",
                name="Mod A",
            )
            row = store.get_module("mod-a")
            assert row is not None
            self.assertEqual(row["adapter"], "SKILL_PACK")
            self.assertEqual(row["active_version_id"], "mod-a:v1")
            ver = store.get_version("mod-a:v1")
            assert ver is not None
            self.assertEqual(ver["module_id"], "mod-a")

    def test_pip_editable_dot_uses_install_root(self) -> None:
        from Data.modules.module_manager.external.install import InstallationService
        from Data.modules.module_manager.external.types import parse_external_config

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\nname="tinydemo"\nversion="0.0.1"\n'
                'requires-python=">=3.10"\n',
                encoding="utf-8",
            )
            (root / "tinydemo").mkdir()
            (root / "tinydemo" / "__init__.py").write_text("", encoding="utf-8")
            cfg = parse_external_config(
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(root),
                    "install": {
                        "strategy": ["PIP_PACKAGE"],
                        "python_packages": ["-e", "."],
                    },
                    "runtime": {"command": ["python3", "-c", "print(1)"]},
                }
            )
            assert cfg is not None
            svc = InstallationService(Path(tmp) / "data")
            # Create venv under checkout so pip is local (not system externally-managed).
            svc._python_venv(root, cfg)  # noqa: SLF001
            info = svc._pip_packages(root, cfg)  # noqa: SLF001
            self.assertTrue(info.get("editable"))
            self.assertEqual(info.get("cwd"), str(root))
            self.assertTrue((root / ".venv").exists())

    def test_cli_operation_defaults_fill_placeholders(self) -> None:
        from Data.modules.module_manager.external.adapters.base import AdapterContext
        from Data.modules.module_manager.external.adapters.cli import CliAdapter
        from Data.modules.module_manager.external.types import parse_external_config

        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / "echo_tool.py"
            tool.write_text(
                "import sys\nprint(' '.join(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            cfg = parse_external_config(
                {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "operations": [
                            {
                                "name": "greet",
                                "command": [sys.executable, str(tool), "{name}", "{style}"],
                                "defaults": {"name": "world", "style": "plain"},
                            }
                        ]
                    },
                    "result": {"format": "text"},
                }
            )
            assert cfg is not None
            adapter = CliAdapter(
                AdapterContext(module_id="echo", config=cfg, install_root=tmp, data_root=tmp)
            )
            argv = adapter._build_argv("greet", {})  # noqa: SLF001
            self.assertEqual(argv[-2:], ["world", "plain"])
            argv2 = adapter._build_argv("greet", {"name": "leviathan"})  # noqa: SLF001
            self.assertEqual(argv2[-2:], ["leviathan", "plain"])
            with self.assertRaises(FileNotFoundError):
                adapter._render_argv(["{missing}"], {})  # noqa: SLF001


class ExternalFabricDoDProofTests(unittest.TestCase):
    """Closable DoD proofs: cognition cancel, SSE events, assim job, process reconcile."""

    def test_cognition_cancel_propagates_to_external_cli(self) -> None:
        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "slow"
            root.mkdir(parents=True)
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
                    {
                        "capability_id": "external.slow.run",
                        "name": "Run",
                        "external_name": "run",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize("slow", ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp))
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            managed = manager.get("slow")
            assert managed is not None
            register_external_module_capabilities(
                catalog=catalog, plugin_registry=plugins, managed=managed
            )
            gateway = ExecutionGateway(catalog=catalog)
            gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
            runtime = CognitiveRuntime(enabled=True, execution_gateway=gateway, factuality_mode="NONE")
            task = TaskModel(
                task_id="t1",
                run_id="r1",
                raw_request="run slow",
                goal="run slow",
                domain="test",
                task_type="tool",
            )
            state = CognitiveRunState(
                run_id="r1",
                task=task,
                status=CognitiveRunStatus.REASONING,
                trace_id="tr-1",
            )

            def _cancel_later() -> None:
                time.sleep(0.25)
                state.cancel_requested = True

            threading.Thread(target=_cancel_later, daemon=True).start()
            action = CognitiveAction(
                kind=CognitiveActionKind.INVOKE_CAPABILITY,
                action_id="a-slow-1",
                capability_id="external.slow.run",
                arguments={},
            )
            obs = runtime._execute_action(state, action, history=[])  # noqa: SLF001
            self.assertEqual(obs.kind.value, "TOOL_RESULT")
            result = (obs.payload or {}).get("result") or {}
            self.assertEqual(str(result.get("status")), "CANCELLED")
            event_types = [e.get("event_type") for e in state.events]
            self.assertIn("tool.started", event_types)
            self.assertTrue(
                "tool.failed" in event_types or "tool.completed" in event_types,
                msg=f"events={event_types}",
            )
            self.assertTrue(
                any(e.get("event_type") == "tool.progress" for e in state.events),
                msg=f"expected tool.progress in {event_types}",
            )

    def test_cognition_emits_rich_operational_sse_events(self) -> None:
        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )

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
                    "assimilation_mode": "NONE",
                    "runtime": {
                        "command": [sys.executable, str(tool), "{query}"],
                        "operations": [
                            {"name": "search", "command": [sys.executable, str(tool), "{query}"]}
                        ],
                    },
                    "result": {"format": "json"},
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
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-cli", ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp)
            )
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            managed = manager.get("fake-cli")
            assert managed is not None
            register_external_module_capabilities(
                catalog=catalog, plugin_registry=plugins, managed=managed
            )
            gateway = ExecutionGateway(catalog=catalog)
            gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
            runtime = CognitiveRuntime(enabled=True, execution_gateway=gateway, factuality_mode="NONE")
            task = TaskModel(
                task_id="t2",
                run_id="r2",
                raw_request="search x",
                goal="search x",
                domain="test",
                task_type="tool",
            )
            state = CognitiveRunState(
                run_id="r2",
                task=task,
                status=CognitiveRunStatus.REASONING,
                trace_id="tr-2",
            )
            obs = runtime._execute_action(  # noqa: SLF001
                state,
                CognitiveAction(
                    kind=CognitiveActionKind.INVOKE_CAPABILITY,
                    action_id="a-search-1",
                    capability_id="external.fake_cli.search",
                    arguments={"query": "leviathan"},
                ),
                history=[],
            )
            self.assertTrue(obs.success)
            event_types = [e.get("event_type") for e in state.events]
            for required in (
                "module.starting",
                "tool.started",
                "tool.completed",
                "module.ready",
                "source.observed",
            ):
                self.assertIn(required, event_types, msg=f"missing {required} in {event_types}")
            # Rich capability result for CapabilityResultCards (parts/sources/module_id).
            result = (obs.payload or {}).get("result") or {}
            output = result.get("output") if isinstance(result.get("output"), dict) else {}
            meta = output.get("metadata") if isinstance(output.get("metadata"), dict) else {}
            self.assertEqual(meta.get("module_id"), "fake-cli")
            self.assertTrue(output.get("parts"), msg="expected result parts")
            self.assertTrue(output.get("source_refs"), msg="expected source_refs")
            self.assertIn("source.observed", event_types)

    def test_assimilation_queues_job_runtime(self) -> None:
        from Data.modules.module_manager.external.post_result import queue_or_run_assimilation
        from Data.modules.module_manager.external.types import AssimilationMode

        enqueued: list[Any] = []

        class _Job:
            job_id = "job-assim-1"

        class _JR:
            def enqueue(self, request):  # noqa: ANN001
                enqueued.append(request)
                return _Job()

        out = queue_or_run_assimilation(
            mode=AssimilationMode.KNOWLEDGE_CANDIDATE,
            capability_id="external.agent_reach.search",
            module_id="agent-reach",
            request_id="req-assim-unique-1",
            run_id="run-1",
            job_id=None,
            output={
                "summary": "found sources",
                "source_refs": [{"title": "A", "url": "https://example.com/a", "published_at": "2026-01-01T00:00:00Z"}],
                "metadata": {"retrieved_at": "2026-09-27T12:00:00Z"},
            },
            status="COMPLETED",
            job_runtime=_JR(),
            assimilation_service=None,
        )
        self.assertTrue(out.get("queued"))
        self.assertEqual(out.get("job_id"), "job-assim-1")
        self.assertEqual(len(enqueued), 1)
        self.assertEqual(enqueued[0].capability_id, "external.knowledge.assimilate")

    def test_process_service_reconciles_dead_pid(self) -> None:
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
            store = ExternalCapabilityStore(db)
            store.initialize()
            store.upsert_module(
                module_id="fake-svc",
                name="Fake Service",
                adapter="PROCESS_SERVICE",
                runtime_state="RUNNING",
                desired_state="RUNNING",
            )
            # Dead PID + non-matching fingerprint must reconcile to STOPPED.
            store.upsert_process(
                module_id="fake-svc",
                pid=999999,
                fingerprint="bogus-fingerprint",
                command=[sys.executable, str(server), str(port)],
                cwd=str(server.parent),
                health="OK",
            )
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-svc",
                ModuleContext(
                    database_path=str(db),
                    data_root=tmp,
                    metadata={"external_capability_store": store},
                ),
            )
            # Do not ensure_ready/start — prove restart reconcile on dead PID alone.
            inst = manager.get("fake-svc")
            assert inst is not None and inst.instance is not None
            adapter = inst.instance._adapter  # noqa: SLF001
            adapter._owned = None  # noqa: SLF001
            adapter._reconcile_persisted()  # noqa: SLF001
            from Data.modules.module_manager.external.types import ExternalRuntimeState

            self.assertEqual(adapter.runtime_state(), ExternalRuntimeState.STOPPED)
            proc = store.get_process("fake-svc")
            assert proc is not None
            self.assertEqual(proc.get("health"), "RECONCILED_DEAD")
            self.assertIsNone(proc.get("pid"))


if __name__ == "__main__":
    unittest.main()
