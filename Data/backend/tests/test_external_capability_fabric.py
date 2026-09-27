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

    def test_process_service_port_in_use_fails_closed(self) -> None:
        """Do not treat another listener's ready probe as our module starting."""
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from Data.modules.module_manager.manager import ModuleManagerError

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # noqa: ANN401
                return

            def do_GET(self) -> None:  # noqa: N802
                body = b'{"ok":true,"owner":"intruder"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        port = _free_port()
        server = HTTPServer(("127.0.0.1", port), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "port-clash"
                root.mkdir(parents=True)
                # Command would never be reached if port guard works.
                bogus = Path(tmp) / "never.py"
                bogus.write_text("raise SystemExit('should not start')\n", encoding="utf-8")
                manifest = {
                    "module_id": "port-clash",
                    "name": "Port Clash",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "PROCESS_SERVICE",
                        "source_type": "path",
                        "path": str(tmp),
                        "install": {"strategy": "NONE"},
                        "runtime": {
                            "mode": "LAZY",
                            "command": [sys.executable, str(bogus)],
                            "startup_timeout_seconds": 5,
                            "base_url": f"http://127.0.0.1:{port}",
                            "ready_probe": {
                                "kind": "http",
                                "url": f"http://127.0.0.1:{port}/health",
                                "expect_status": 200,
                            },
                        },
                    },
                    "capabilities": [],
                }
                (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
                manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
                manager.discover()
                manager.initialize(
                    "port-clash",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                with self.assertRaises(ModuleManagerError) as ctx:
                    manager.start("port-clash")
                self.assertIn("PORT_IN_USE", str(ctx.exception))
        finally:
            server.shutdown()
            server.server_close()

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

    def test_http_requires_agent_runtime_returns_not_available(self) -> None:
        """Gated HTTP ops must not surface opaque 404 when agent runtime is disabled."""
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # noqa: ANN401
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/api/agent/runtime"):
                    body = b'{"enabled":false,"runtimeEnabled":false}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        port = _free_port()
        server = HTTPServer(("127.0.0.1", port), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "gated-http"
                root.mkdir(parents=True)
                manifest = {
                    "module_id": "gated-http",
                    "name": "Gated HTTP",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "HTTP_OPENAPI",
                        "source_type": "none",
                        "install": {"strategy": "NONE"},
                        "runtime": {
                            "base_url": f"http://127.0.0.1:{port}",
                            "operations": [
                                {
                                    "name": "list_skills",
                                    "method": "GET",
                                    "path": "/api/agent/skills",
                                    "metadata": {
                                        "requires_agent_runtime": True,
                                        "preflight_path": "/api/agent/runtime",
                                    },
                                }
                            ],
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.gated_http.list_skills",
                            "name": "List Skills",
                            "external_name": "list_skills",
                            "side_effects": ["NETWORK"],
                        }
                    ],
                }
                (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
                manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
                manager.discover()
                manager.initialize(
                    "gated-http",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                result = manager.execute("gated-http", "list_skills", {})
                self.assertEqual(result.status, "FAILED", msg=result.error)
                self.assertEqual(result.error, "NOT_AVAILABLE")
                parts = (result.output or {}).get("parts") or []
                err_part = next((p for p in parts if isinstance(p, dict) and p.get("kind") == "ERROR"), {})
                self.assertEqual(err_part.get("code"), "NOT_AVAILABLE", msg=result.output)
                self.assertEqual(err_part.get("reason"), "agent_runtime_disabled", msg=result.output)
        finally:
            server.shutdown()
            server.server_close()

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

    def test_composite_declared_cli_ops_beat_skill_search_name(self) -> None:
        """COMPOSITE: runtime.operations names must not be swallowed by skill-pack 'search'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fake-comp-search"
            root.mkdir(parents=True)
            tool = FIXTURES / "fake_cli" / "tool.py"
            skill_dir = root / "skills" / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: demo\ndescription: skill search decoy\n---\n# Demo\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "fake-comp-search",
                "name": "Fake Comp Search",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "COMPOSITE",
                    "children": ["SKILL_PACK", "CLI"],
                    "source_type": "path",
                    "path": str(root),
                    "install": {"strategy": "NONE"},
                    "skill_roots": ["skills"],
                    "runtime": {
                        "operations": [
                            {
                                "name": "search",
                                "command": [sys.executable, str(tool), "{query}"],
                            }
                        ]
                    },
                    "result": {"format": "text"},
                },
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fake-comp-search",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("fake-comp-search")
            cli_search = manager.execute("fake-comp-search", "search", {"query": "needle"})
            self.assertEqual(cli_search.status, "COMPLETED")
            # Skill search remains available under search_skills alias.
            skills = manager.execute("fake-comp-search", "search_skills", {"query": "demo"})
            self.assertEqual(skills.status, "COMPLETED")

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
        from Data.modules.mcp.module_integration import register_module_mcp

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
                "mcp": {
                    "servers": [
                        {
                            "server_id": "fake-mcp",
                            "display_name": "Fake MCP",
                            "transport": "stdio",
                            "command": sys.executable,
                            "args": [str(fake), "--mode=normal"],
                            "cwd": "$INSTALL_ROOT",
                            "enabled": True,
                            "eager_connect": False,
                            "trust": "untrusted",
                        }
                    ]
                },
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            # server_id/display_name (no legacy "name") must register + resolve $INSTALL_ROOT
            registered = register_module_mcp(
                bridge,
                module_id="fake-mcp",
                manifest_path=str(root / "module.json"),
                install_root=str(pkg),
            )
            self.assertEqual(len(registered), 1)
            self.assertEqual(registered[0].server_id, "fake-mcp")
            self.assertEqual(registered[0].cwd, str(pkg))
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
            # Instructions must not be present in shortlist metadata.
            meta = short.inspected["skill:scroll-demo"].get("metadata") or {}
            self.assertTrue(meta.get("on_demand_instructions"))
            self.assertNotIn("instructions", short.inspected["skill:scroll-demo"])

    def test_cognition_search_capability_selects_skills_from_store(self) -> None:
        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = ExternalCapabilityStore(Path(tmp) / "c.db")
            store.initialize()
            store.upsert_skill(
                {
                    "skill_id": "cloudflare-audit",
                    "name": "cloudflare-security-audit",
                    "description": "Audit Cloudflare Worker security configuration",
                    "source_repo": "cloudflare/security-audit-skill",
                    "content_hash": "hash1",
                    "enabled": True,
                    "catalog_only": False,
                    "trigger_description": "audit cloudflare worker",
                }
            )
            runtime = CognitiveRuntime(enabled=True, factuality_mode="NONE")
            runtime.broker._skill_store = store  # type: ignore[attr-defined]
            task = TaskModel(
                task_id="t-skill",
                run_id="r-skill",
                raw_request="Audit this Cloudflare Worker",
                goal="Audit this Cloudflare Worker",
                domain="security",
                task_type="skill",
            )
            state = CognitiveRunState(
                run_id="r-skill",
                task=task,
                status=CognitiveRunStatus.REASONING,
            )
            obs = runtime._execute_action(  # noqa: SLF001
                state,
                CognitiveAction(
                    kind=CognitiveActionKind.SEARCH_CAPABILITY,
                    action_id="a-search-skills",
                    arguments={},
                ),
                history=[],
            )
            self.assertTrue(obs.success)
            ids = list((obs.payload or {}).get("capability_ids") or [])
            self.assertTrue(any(str(i).startswith("skill:") for i in ids), msg=ids)
            self.assertIn("skill:cloudflare-audit", ids)
            event_types = [e.get("event_type") for e in state.events]
            self.assertIn("capability_searched", event_types)


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
            with self.assertRaises(Exception) as blocked:
                manager.activate_version("fake-cli", v2["version_id"])
            self.assertIn("UPDATE_BLOCKED_ACTIVE", str(blocked.exception))
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

    def test_install_only_cli_status_without_hanging_invoke(self) -> None:
        """Interactive/install-only CLIs: status is lifecycle; unknown ops are CAPABILITY_NOT_FOUND."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "ghosty"
            root.mkdir(parents=True)
            (root / "README.md").write_text("install only\n", encoding="utf-8")
            manifest = {
                "module_id": "ghosty",
                "name": "Ghosty",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(root),
                    "install": {"strategy": "NONE"},
                    "runtime": {"mode": "EPHEMERAL", "operations": []},
                    "result": {"format": "text"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.ghosty.status",
                        "name": "Status",
                        "external_name": "status",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "ghosty",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("ghosty")
            status = manager.execute("ghosty", "status", {})
            self.assertEqual(status.status, "COMPLETED")
            self.assertIn((status.output or {}).get("status"), {"READY", "INITIALIZED", "LOADED"})
            missing = manager.execute("ghosty", "run", {})
            self.assertEqual(missing.status, "FAILED")
            self.assertEqual(missing.error, "CAPABILITY_NOT_FOUND")

    def test_ghosttrack_style_declarative_public_api_cli_ops(self) -> None:
        """GhostTrack machine path: declarative curl argv + placeholders — no TUI wrapper."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "ghosttrack-style"
            root.mkdir(parents=True)
            fake_curl = root / "fake_curl.py"
            fake_curl.write_text(
                "import sys\n"
                "url = sys.argv[-1]\n"
                "if 'ipwho.is' in url:\n"
                "    ip = url.rsplit('/', 1)[-1]\n"
                "    print('{\"ip\":\"%s\",\"success\":true,\"country\":\"Testland\"}' % ip)\n"
                "elif 'ipify' in url:\n"
                "    print('203.0.113.9')\n"
                "else:\n"
                "    print('unexpected', url); raise SystemExit(2)\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "ghosttrack-style",
                "name": "GhostTrack Style",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(root),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "mode": "EPHEMERAL",
                        "operations": [
                            {
                                "name": "ip_lookup",
                                "command": [
                                    sys.executable,
                                    str(fake_curl),
                                    "http://ipwho.is/{ip}",
                                ],
                                "result_format": "json",
                            },
                            {
                                "name": "show_ip",
                                "command": [
                                    sys.executable,
                                    str(fake_curl),
                                    "https://api.ipify.org/",
                                ],
                                "result_format": "text",
                            },
                        ],
                    },
                    "result": {"format": "MIXED"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.ghosttrack-style.ip_lookup",
                        "name": "IP Lookup",
                        "external_name": "ip_lookup",
                        "side_effects": ["READ", "NETWORK"],
                    },
                    {
                        "capability_id": "external.ghosttrack-style.show_ip",
                        "name": "Show IP",
                        "external_name": "show_ip",
                        "side_effects": ["READ", "NETWORK"],
                    },
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "ghosttrack-style",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            manager.ensure_installed("ghosttrack-style")
            show = manager.execute("ghosttrack-style", "show_ip", {})
            self.assertEqual(show.status, "COMPLETED", msg=show.error)
            self.assertIn("203.0.113.9", str((show.output or {}).get("summary") or ""))
            lookup = manager.execute("ghosttrack-style", "ip_lookup", {"ip": "8.8.8.8"})
            self.assertEqual(lookup.status, "COMPLETED", msg=lookup.error)
            structured = (lookup.output or {}).get("structured_data") or {}
            self.assertEqual(structured.get("ip"), "8.8.8.8")
            self.assertTrue(structured.get("success"))

    def test_cli_accept_exit_codes_treats_nonzero_as_success(self) -> None:
        """Declarative accept_exit_codes keeps honest stdout when CLI exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "alpha-ish"
            root.mkdir(parents=True)
            tool = Path(tmp) / "status.py"
            tool.write_text(
                "import sys\nprint('not logged in')\nsys.exit(1)\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "alpha-ish",
                "name": "Alpha Ish",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "operations": [
                            {
                                "name": "status",
                                "command": [sys.executable, str(tool)],
                                "accept_exit_codes": [0, 1],
                                "result_format": "text",
                            }
                        ]
                    },
                    "result": {"format": "text"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.alpha_ish.status",
                        "name": "Status",
                        "external_name": "status",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "alpha-ish",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            result = manager.execute("alpha-ish", "status", {})
            self.assertEqual(result.status, "COMPLETED", msg=result.error)
            self.assertIn("not logged in", str((result.output or {}).get("summary") or ""))
            meta = (result.output or {}).get("metadata") or {}
            self.assertEqual(meta.get("exit_code"), 1)
            self.assertTrue(meta.get("accepted_nonzero_exit"))

    def test_executor_emits_external_observability_metrics(self) -> None:
        """external.invocations / modules.discovered must reach ObservabilityHub."""

        class _CaptureHub:
            def __init__(self) -> None:
                self.events: list[tuple[str, str, dict[str, Any]]] = []

            def emit(self, category: str, name: str, *, payload: dict[str, Any] | None = None, **_: Any) -> None:
                self.events.append((category, name, dict(payload or {})))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "metric-cli"
            root.mkdir(parents=True)
            tool = Path(tmp) / "echo.py"
            tool.write_text(
                "import json,sys\nprint(json.dumps({'ok':True,'q':sys.argv[1]}))\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "metric-cli",
                "name": "Metric CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "operations": [
                            {
                                "name": "search",
                                "command": [sys.executable, str(tool), "{query}"],
                                "result_format": "json",
                            }
                        ]
                    },
                    "result": {"format": "JSON"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.metric_cli.search",
                        "name": "Metric Search",
                        "external_name": "search",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "metric-cli",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            hub = _CaptureHub()
            catalog = CapabilityCatalog()
            register_external_control_capabilities(catalog)
            plugins = PluginRegistry(catalog)
            managed = manager.get("metric-cli")
            assert managed is not None
            register_external_module_capabilities(catalog=catalog, plugin_registry=plugins, managed=managed)
            gateway = ExecutionGateway(
                catalog=catalog,
                module_executor=ExternalModuleExecutor(manager, observability=hub),
            )
            result = gateway.execute(
                CapabilityRequest(
                    capability_id="external.metric_cli.search",
                    arguments={"query": "obs"},
                    requested_by="test",
                )
            )
            self.assertEqual(result.status.value, "COMPLETED", msg=result.error)
            names = [n for _, n, _ in hub.events]
            self.assertIn("external.invocations", names, msg=hub.events)
            self.assertIn("external.bytes_output", names, msg=hub.events)
            self.assertIn("external.modules.running", names, msg=hub.events)
            self.assertIn("external.modules.discovered", names, msg=hub.events)
            self.assertTrue(
                any(c == "external_capability" for c, _, _ in hub.events),
                msg=hub.events,
            )

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

    def test_cli_json_payload_placeholder_and_op_timeout(self) -> None:
        from Data.modules.module_manager.external.adapters.base import AdapterContext
        from Data.modules.module_manager.external.adapters.cli import CliAdapter

        cfg = parse_external_config(
            {
                "adapter": "CLI",
                "source_type": "path",
                "path": "/tmp",
                "install": {"strategy": "NONE"},
                "runtime": {
                    "timeout_seconds": 300,
                    "operations": [
                        {
                            "name": "analyze",
                            "timeout_seconds": 12,
                            "command": ["python", "cli.py", "{command}", "?{payload}"],
                            "defaults": {"command": "get_key_metrics"},
                        }
                    ],
                },
            }
        )
        assert cfg is not None
        adapter = CliAdapter(AdapterContext(module_id="fin", config=cfg, install_root="/tmp", data_root="/tmp"))
        argv = adapter._build_argv(  # noqa: SLF001
            "analyze",
            {"command": "get_key_metrics", "payload": '{"company":{"ticker":"X"}}'},
        )
        self.assertEqual(argv[-1], '{"company":{"ticker":"X"}}')
        argv_no_payload = adapter._build_argv("analyze", {"command": "get_key_metrics"})  # noqa: SLF001
        self.assertEqual(argv_no_payload[-1], "get_key_metrics")
        op = adapter._operation_config("analyze")  # noqa: SLF001
        self.assertEqual(op.get("timeout_seconds"), 12)


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

    def test_cognition_cancel_via_job_runtime_offload(self) -> None:
        """Cancel must reach child CLI through JobRuntime cancel flags + gateway probe."""
        import os

        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "slow-job"
                root.mkdir(parents=True)
                slow = Path(tmp) / "slow_job.py"
                slow.write_text("import time\ntime.sleep(60)\nprint('late')\n", encoding="utf-8")
                manifest = {
                    "module_id": "slow-job",
                    "name": "Slow Job",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "CLI",
                        "source_type": "path",
                        "path": str(tmp),
                        "install": {"strategy": "NONE"},
                        "resource_class": "CPU_HEAVY",
                        "runtime": {
                            "operations": [
                                {
                                    "name": "run",
                                    "command": [sys.executable, str(slow)],
                                }
                            ],
                            "timeout_seconds": 90,
                        },
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.slow_job.run",
                            "name": "Run",
                            "external_name": "run",
                            "side_effects": ["READ"],
                        }
                    ],
                }
                (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
                manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
                manager.discover()
                manager.initialize(
                    "slow-job",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                catalog = CapabilityCatalog()
                plugins = PluginRegistry(catalog)
                managed = manager.get("slow-job")
                assert managed is not None
                register_external_module_capabilities(
                    catalog=catalog, plugin_registry=plugins, managed=managed
                )
                gateway = ExecutionGateway(catalog=catalog)
                gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
                job_store = JobStore(Path(tmp) / "jobs.db")
                job_store.initialize()
                jobs = JobRuntime(job_store, gateway, ResourceManager(2))
                # JobRuntime auto-wires gateway._job_cancel_check when absent.
                self.assertTrue(callable(getattr(gateway, "_job_cancel_check", None)))
                runtime = CognitiveRuntime(
                    enabled=True,
                    execution_gateway=gateway,
                    job_runtime=jobs,
                    factuality_mode="NONE",
                )
                task = TaskModel(
                    task_id="t-cancel-job",
                    run_id="r-cancel-job",
                    raw_request="run slow job",
                    goal="run slow job",
                    domain="test",
                    task_type="tool",
                )
                state = CognitiveRunState(
                    run_id="r-cancel-job",
                    task=task,
                    status=CognitiveRunStatus.REASONING,
                    trace_id="tr-cancel-job",
                )

                def _cancel_later() -> None:
                    time.sleep(0.35)
                    state.cancel_requested = True

                threading.Thread(target=_cancel_later, daemon=True).start()
                action = CognitiveAction(
                    kind=CognitiveActionKind.INVOKE_CAPABILITY,
                    action_id="a-cancel-job-1",
                    capability_id="external.slow_job.run",
                    arguments={},
                )
                obs = runtime._execute_action(state, action, history=[])  # noqa: SLF001
                assert obs is not None
                result = (obs.payload or {}).get("result") or {}
                self.assertEqual(str(result.get("status")), "CANCELLED", msg=result)
                tele = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
                self.assertEqual(tele.get("executed_via"), "job_runtime")
                event_types = [e.get("event_type") for e in state.events]
                self.assertIn("job.started", event_types)
                self.assertTrue(
                    any(
                        e.get("event_type") == "job.progress"
                        and (e.get("payload") or {}).get("status") == "CANCEL_REQUESTED"
                        for e in state.events
                    ),
                    msg=f"events={event_types}",
                )
                jobs.stop_background_worker()
        finally:
            if prev is None:
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            else:
                os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = prev

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
        obs_events: list[str] = []

        class _Job:
            job_id = "job-assim-1"

        class _JR:
            def enqueue(self, **kwargs):  # noqa: ANN003
                enqueued.append(kwargs)
                return _Job()

        class _Obs:
            def emit(self, category: str, name: str, **_: Any) -> None:
                obs_events.append(name)

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
            observability=_Obs(),
        )
        self.assertTrue(out.get("queued"))
        self.assertEqual(out.get("job_id"), "job-assim-1")
        self.assertEqual(len(enqueued), 1)
        self.assertEqual(enqueued[0]["capability_id"], "external.knowledge.assimilate")
        self.assertIn("knowledge.assimilation_queued", obs_events)
        self.assertIn("assimilation.queued", obs_events)

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

    def test_cognition_offloads_external_required_via_job_runtime(self) -> None:
        """EXTERNAL_REQUIRED MODULE caps must enqueue JobRuntime, not fail REJECTED."""
        import os

        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "heavy-cli"
                root.mkdir(parents=True)
                tool = FIXTURES / "fake_cli" / "tool.py"
                manifest = {
                    "module_id": "heavy-cli",
                    "name": "Heavy CLI",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "CLI",
                        "source_type": "path",
                        "path": str(tool.parent),
                        "install": {"strategy": "NONE"},
                        "resource_class": "NETWORK_HEAVY",
                        "assimilation_mode": "NONE",
                        "runtime": {
                            "command": [sys.executable, str(tool), "{query}"],
                            "operations": [
                                {
                                    "name": "search",
                                    "command": [sys.executable, str(tool), "{query}"],
                                }
                            ],
                            "timeout_seconds": 30,
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.heavy_cli.search",
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
                    "heavy-cli",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                catalog = CapabilityCatalog()
                plugins = PluginRegistry(catalog)
                managed = manager.get("heavy-cli")
                assert managed is not None
                register_external_module_capabilities(
                    catalog=catalog, plugin_registry=plugins, managed=managed
                )
                defn = catalog.get("external.heavy_cli.search")
                assert defn is not None
                self.assertEqual(
                    (defn.metadata or {}).get("execution_class"),
                    "EXTERNAL_REQUIRED",
                )
                gateway = ExecutionGateway(catalog=catalog)
                gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
                # Prove API-inline is rejected first.
                rejected = gateway.execute(
                    CapabilityRequest(
                        capability_id="external.heavy_cli.search",
                        arguments={"query": "hello"},
                        requested_by="api",
                    )
                )
                self.assertEqual(rejected.status.value, "REJECTED")
                self.assertEqual((rejected.telemetry or {}).get("reason"), "worker_required")

                job_store = JobStore(Path(tmp) / "jobs.db")
                job_store.initialize()
                jobs = JobRuntime(job_store, gateway, ResourceManager(2))
                runtime = CognitiveRuntime(
                    enabled=True,
                    execution_gateway=gateway,
                    job_runtime=jobs,
                    factuality_mode="NONE",
                )
                task = TaskModel(
                    task_id="t-heavy",
                    run_id="r-heavy",
                    raw_request="search hello",
                    goal="search hello",
                    domain="test",
                    task_type="tool",
                )
                state = CognitiveRunState(
                    run_id="r-heavy",
                    task=task,
                    status=CognitiveRunStatus.REASONING,
                    trace_id="tr-heavy",
                )
                action = CognitiveAction(
                    kind=CognitiveActionKind.INVOKE_CAPABILITY,
                    action_id="a-heavy-1",
                    capability_id="external.heavy_cli.search",
                    arguments={"query": "hello"},
                )
                obs = runtime._execute_action(state, action, history=[])  # noqa: SLF001
                assert obs is not None
                self.assertEqual(obs.kind.value, "TOOL_RESULT")
                result = (obs.payload or {}).get("result") or {}
                self.assertEqual(str(result.get("status")), "COMPLETED", msg=result)
                tele = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
                self.assertEqual(tele.get("executed_via"), "job_runtime")
                self.assertTrue(tele.get("job_id"))
                event_types = [e.get("event_type") for e in state.events]
                self.assertIn("job.started", event_types)
                self.assertIn("job.completed", event_types)
                jobs.stop_background_worker()
        finally:
            if prev is None:
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            else:
                os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = prev

    def test_cognition_iterative_multi_tool_external_required(self) -> None:
        """Plan → tool A → observe → tool B via JobRuntime offload (no API-thread block)."""
        import os

        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                mods = Path(tmp) / "mods"
                tool = FIXTURES / "fake_cli" / "tool.py"
                for mid, cap in (("tool-a", "external.tool_a.search"), ("tool-b", "external.tool_b.search")):
                    root = mods / mid
                    root.mkdir(parents=True)
                    manifest = {
                        "module_id": mid,
                        "name": mid,
                        "version": "0.0.1",
                        "entrypoint": FACTORY,
                        "external": {
                            "adapter": "CLI",
                            "source_type": "path",
                            "path": str(tool.parent),
                            "install": {"strategy": "NONE"},
                            "resource_class": "NETWORK_HEAVY",
                            "assimilation_mode": "NONE",
                            "runtime": {
                                "operations": [
                                    {
                                        "name": "search",
                                        "command": [sys.executable, str(tool), "{query}"],
                                    }
                                ],
                                "timeout_seconds": 30,
                            },
                            "result": {"format": "json"},
                        },
                        "capabilities": [
                            {
                                "capability_id": cap,
                                "name": "Search",
                                "external_name": "search",
                                "side_effects": ["READ"],
                            }
                        ],
                    }
                    (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")

                manager = ModuleManager(discovery_roots=(mods,), enabled=True)
                manager.discover()
                catalog = CapabilityCatalog()
                plugins = PluginRegistry(catalog)
                for mid in ("tool-a", "tool-b"):
                    manager.initialize(
                        mid,
                        ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                    )
                    managed = manager.get(mid)
                    assert managed is not None
                    register_external_module_capabilities(
                        catalog=catalog, plugin_registry=plugins, managed=managed
                    )
                gateway = ExecutionGateway(catalog=catalog)
                gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
                job_store = JobStore(Path(tmp) / "jobs.db")
                job_store.initialize()
                jobs = JobRuntime(job_store, gateway, ResourceManager(2))
                runtime = CognitiveRuntime(
                    enabled=True,
                    execution_gateway=gateway,
                    job_runtime=jobs,
                    factuality_mode="NONE",
                )
                task = TaskModel(
                    task_id="t-multi",
                    run_id="r-multi",
                    raw_request="use both tools",
                    goal="use both tools",
                    domain="test",
                    task_type="tool",
                )
                state = CognitiveRunState(
                    run_id="r-multi",
                    task=task,
                    status=CognitiveRunStatus.REASONING,
                    trace_id="tr-multi",
                )
                for i, cap in enumerate(("external.tool_a.search", "external.tool_b.search")):
                    # Iterative loop returns to REASONING between tool observations.
                    state.status = CognitiveRunStatus.REASONING
                    action = CognitiveAction(
                        kind=CognitiveActionKind.INVOKE_CAPABILITY,
                        action_id=f"a-multi-{i}",
                        capability_id=cap,
                        arguments={"query": f"q{i}"},
                    )
                    obs = runtime._execute_action(state, action, history=[])  # noqa: SLF001
                    assert obs is not None
                    result = (obs.payload or {}).get("result") or {}
                    self.assertEqual(str(result.get("status")), "COMPLETED", msg=result)
                    tele = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
                    self.assertEqual(tele.get("executed_via"), "job_runtime")
                    self.assertEqual(state.status, CognitiveRunStatus.OBSERVING)
                event_types = [e.get("event_type") for e in state.events]
                self.assertGreaterEqual(event_types.count("job.started"), 2)
                self.assertGreaterEqual(event_types.count("job.completed"), 2)
                self.assertGreaterEqual(event_types.count("tool.completed"), 2)
                jobs.stop_background_worker()
        finally:
            if prev is None:
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            else:
                os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = prev

    def test_cognition_offloads_external_preferred_module_when_externalized(self) -> None:
        """EXTERNAL_PREFERRED MODULE CLI must not run inline when externalize=on."""
        import os

        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "pref-cli"
                root.mkdir(parents=True)
                tool = FIXTURES / "fake_cli" / "tool.py"
                manifest = {
                    "module_id": "pref-cli",
                    "name": "Pref CLI",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "CLI",
                        "source_type": "path",
                        "path": str(tool.parent),
                        "install": {"strategy": "NONE"},
                        "assimilation_mode": "NONE",
                        "runtime": {
                            "operations": [
                                {
                                    "name": "search",
                                    "command": [sys.executable, str(tool), "{query}"],
                                }
                            ],
                            "timeout_seconds": 30,
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.pref_cli.search",
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
                    "pref-cli",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                catalog = CapabilityCatalog()
                plugins = PluginRegistry(catalog)
                managed = manager.get("pref-cli")
                assert managed is not None
                register_external_module_capabilities(
                    catalog=catalog, plugin_registry=plugins, managed=managed
                )
                defn = catalog.get("external.pref_cli.search")
                assert defn is not None
                self.assertEqual(
                    (defn.metadata or {}).get("execution_class"),
                    "EXTERNAL_PREFERRED",
                )
                gateway = ExecutionGateway(catalog=catalog)
                gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
                # Gateway still allows PREFERRED inline — Cognition must choose JobRuntime.
                inline = gateway.execute(
                    CapabilityRequest(
                        capability_id="external.pref_cli.search",
                        arguments={"query": "hello"},
                        requested_by="api",
                    )
                )
                self.assertEqual(inline.status.value, "COMPLETED")

                job_store = JobStore(Path(tmp) / "jobs.db")
                job_store.initialize()
                jobs = JobRuntime(job_store, gateway, ResourceManager(2))
                runtime = CognitiveRuntime(
                    enabled=True,
                    execution_gateway=gateway,
                    job_runtime=jobs,
                    factuality_mode="NONE",
                )
                task = TaskModel(
                    task_id="t-pref",
                    run_id="r-pref",
                    raw_request="search",
                    goal="search",
                    domain="test",
                    task_type="tool",
                )
                state = CognitiveRunState(
                    run_id="r-pref",
                    task=task,
                    status=CognitiveRunStatus.REASONING,
                    trace_id="tr-pref",
                )
                action = CognitiveAction(
                    kind=CognitiveActionKind.INVOKE_CAPABILITY,
                    action_id="a-pref-1",
                    capability_id="external.pref_cli.search",
                    arguments={"query": "hello"},
                )
                obs = runtime._execute_action(state, action, history=[])  # noqa: SLF001
                assert obs is not None
                result = (obs.payload or {}).get("result") or {}
                self.assertEqual(str(result.get("status")), "COMPLETED", msg=result)
                tele = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
                self.assertEqual(tele.get("executed_via"), "job_runtime")
                self.assertEqual(len(job_store.list(limit=10)), 1)
                self.assertIn("job.started", [e.get("event_type") for e in state.events])
                jobs.stop_background_worker()
        finally:
            if prev is None:
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            else:
                os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = prev

    def test_cognition_emits_capability_discovered_on_search(self) -> None:
        from Data.modules.cognition.capability_broker import CapabilityBroker, CapabilityShortlist
        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )

        class _Broker(CapabilityBroker):
            def shortlist_for_task(self, *, goal: str, domain: str | None = None):  # noqa: ANN001
                return CapabilityShortlist(
                    query=goal,
                    capability_ids=("external.agent_reach.doctor", "skill:scrollcraft"),
                    notes=("test shortlist",),
                )

        runtime = CognitiveRuntime(enabled=True, broker=_Broker(), factuality_mode="NONE")
        task = TaskModel(
            task_id="t-disc",
            run_id="r-disc",
            raw_request="find tools",
            goal="find tools",
            domain="test",
            task_type="tool",
        )
        state = CognitiveRunState(
            run_id="r-disc",
            task=task,
            status=CognitiveRunStatus.REASONING,
            trace_id="tr-disc",
        )
        action = CognitiveAction(
            kind=CognitiveActionKind.SEARCH_CAPABILITY,
            action_id="a-disc",
            arguments={},
        )
        obs = runtime._execute_action(state, action, history=[])  # noqa: SLF001
        assert obs is not None
        self.assertTrue(obs.success)
        discovered = [
            e for e in state.events if e.get("event_type") == "capability.discovered"
        ]
        self.assertEqual(len(discovered), 2)
        ids = {e["payload"]["capability_id"] for e in discovered}
        self.assertEqual(ids, {"external.agent_reach.doctor", "skill:scrollcraft"})

    def test_cognition_job_offload_idempotent_no_duplicate_jobs(self) -> None:
        """Same action_id replays TOOL_RESULT; JobRuntime idempotency_key dedupes enqueue."""
        import os

        from Data.modules.cognition.runtime import CognitiveRunState, CognitiveRuntime
        from Data.modules.cognition.task_model import TaskModel
        from Data.modules.cognition.types import (
            CognitiveAction,
            CognitiveActionKind,
            CognitiveRunStatus,
        )
        from Data.modules.jobs import JobRuntime, JobStore, ResourceManager

        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "idem-cli"
                root.mkdir(parents=True)
                tool = FIXTURES / "fake_cli" / "tool.py"
                manifest = {
                    "module_id": "idem-cli",
                    "name": "Idem CLI",
                    "version": "0.0.1",
                    "entrypoint": FACTORY,
                    "external": {
                        "adapter": "CLI",
                        "source_type": "path",
                        "path": str(tool.parent),
                        "install": {"strategy": "NONE"},
                        "resource_class": "IO_HEAVY",
                        "assimilation_mode": "NONE",
                        "runtime": {
                            "operations": [
                                {
                                    "name": "search",
                                    "command": [sys.executable, str(tool), "{query}"],
                                }
                            ],
                            "timeout_seconds": 30,
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.idem_cli.search",
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
                    "idem-cli",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                catalog = CapabilityCatalog()
                plugins = PluginRegistry(catalog)
                managed = manager.get("idem-cli")
                assert managed is not None
                register_external_module_capabilities(
                    catalog=catalog, plugin_registry=plugins, managed=managed
                )
                gateway = ExecutionGateway(catalog=catalog)
                gateway.module_executor = ExternalModuleExecutor(manager, catalog=catalog)
                job_store = JobStore(Path(tmp) / "jobs.db")
                job_store.initialize()
                jobs = JobRuntime(job_store, gateway, ResourceManager(2))
                runtime = CognitiveRuntime(
                    enabled=True,
                    execution_gateway=gateway,
                    job_runtime=jobs,
                    factuality_mode="NONE",
                )
                task = TaskModel(
                    task_id="t-idem",
                    run_id="r-idem",
                    raw_request="search once",
                    goal="search once",
                    domain="test",
                    task_type="tool",
                )
                state = CognitiveRunState(
                    run_id="r-idem",
                    task=task,
                    status=CognitiveRunStatus.REASONING,
                    trace_id="tr-idem",
                )
                action = CognitiveAction(
                    kind=CognitiveActionKind.INVOKE_CAPABILITY,
                    action_id="a-idem-1",
                    capability_id="external.idem_cli.search",
                    arguments={"query": "once"},
                )
                obs1 = runtime._execute_action(state, action, history=[])  # noqa: SLF001
                assert obs1 is not None
                self.assertEqual(
                    str(((obs1.payload or {}).get("result") or {}).get("status")),
                    "COMPLETED",
                )
                # Main loop appends observations; mirror that for direct _execute_action tests.
                state.observations.append(obs1)
                jobs_after_first = job_store.list(limit=50)
                self.assertEqual(len(jobs_after_first), 1)
                first_job_id = jobs_after_first[0].job_id

                # Replay same action_id — must not enqueue a second job.
                state.status = CognitiveRunStatus.REASONING
                obs2 = runtime._execute_action(state, action, history=[])  # noqa: SLF001
                assert obs2 is not None
                self.assertIs(obs2, obs1)
                jobs_after_replay = job_store.list(limit=50)
                self.assertEqual(len(jobs_after_replay), 1)
                self.assertEqual(jobs_after_replay[0].job_id, first_job_id)
                event_types = [e.get("event_type") for e in state.events]
                self.assertIn("capability_idempotent_replay", event_types)

                # Direct JobRuntime enqueue with same idempotency key returns same record.
                again = jobs.enqueue(
                    capability_id="external.idem_cli.search",
                    arguments={"query": "once"},
                    requested_by="cognition",
                    idempotency_key=f"cog:{state.run_id}:{action.action_id}",
                )
                self.assertEqual(again.job_id, first_job_id)
                self.assertEqual(len(job_store.list(limit=50)), 1)
                jobs.stop_background_worker()
        finally:
            if prev is None:
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            else:
                os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = prev


class ExternalFabricAdversarialArchitectureTests(unittest.TestCase):
    """§117-style architecture invariants — fail closed on parallel systems / wrappers."""

    _FORBIDDEN_OWNERS = (
        "ModuleManagerV2",
        "PluginManagerV2",
        "ExternalToolManagerV2",
        "SkillManagerV2",
        "CapabilityRuntimeV2",
        "ToolRuntimeV2",
        "AgentRuntimeV2",
        "ExecutionGatewayV2",
        "McpBridgeV2",
        "ChatRuntimeV2",
    )

    def test_no_source_specific_wrapper_modules(self) -> None:
        root = Path(__file__).resolve().parents[2]
        hits: list[str] = []
        for path in root.rglob("*Wrapper*.py"):
            rel = str(path.relative_to(root))
            if any(part in rel for part in ("HADES", "editor", "__pycache__", ".venv")):
                continue
            # External fabric must not grow per-repo wrappers.
            if "external" in rel.lower() or path.name.lower().startswith(
                ("osintgram", "ghosttrack", "feynman", "openmaic", "scrollcraft", "selfstarter", "agentreach", "agent_reach")
            ):
                hits.append(rel)
        self.assertEqual(hits, [], msg=f"forbidden wrappers: {hits}")

    def test_no_parallel_v2_owner_modules_under_data(self) -> None:
        root = Path(__file__).resolve().parents[2] / "modules"
        hits: list[str] = []
        for path in root.rglob("*.py"):
            if "HADES" in str(path) or "__pycache__" in str(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in self._FORBIDDEN_OWNERS:
                # Allow strings used only as forbidden-name denylist / audit literals.
                if name not in text:
                    continue
                # assurance.py lists forbidden names as strings — not implementations.
                if path.name == "assurance.py" and f'"{name}"' in text:
                    continue
                if f"class {name}" in text or f"def {name}" in text:
                    hits.append(f"{path}:{name}")
        self.assertEqual(hits, [], msg=f"parallel V2 owners: {hits}")

    def test_external_store_uses_control_sqlite_not_fourth_db(self) -> None:
        from Data.modules.module_manager.external.store import ExternalCapabilityStore

        src = Path(ExternalCapabilityStore.__module__.replace(".", "/") + ".py")
        # Resolve from package root.
        store_path = Path(__file__).resolve().parents[2] / "modules" / "module_manager" / "external" / "store.py"
        text = store_path.read_text(encoding="utf-8")
        self.assertIn("CONTROL", text)
        self.assertNotRegex(text, r"external[_-]tools\.db|fourth.?db", msg=text[:200])
        # Factory path remains ModuleManager external module — not a parallel runtime.
        factory = (
            Path(__file__).resolve().parents[2]
            / "modules"
            / "module_manager"
            / "external"
            / "module.py"
        )
        self.assertTrue(factory.is_file())
        self.assertIn("create_external_capability_module", factory.read_text(encoding="utf-8"))

    def test_shipped_external_capabilities_are_manifest_only(self) -> None:
        root = Path(__file__).resolve().parents[2] / "external_capabilities"
        self.assertTrue(root.is_dir())
        for mod_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            py_files = [p for p in mod_dir.rglob("*.py") if "__pycache__" not in str(p)]
            self.assertEqual(
                py_files,
                [],
                msg=f"{mod_dir.name} must be manifest-only; found {py_files}",
            )
            self.assertTrue((mod_dir / "module.json").is_file(), msg=f"missing module.json in {mod_dir}")


class ExternalFabricRegressionGuardTests(unittest.TestCase):
    """Prove fabric work did not regress PR #191/#192/#193 surfaces."""

    def test_paper_trading_operator_page_still_present(self) -> None:
        root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "trading"
        page = root / "paper" / "PaperTradingPage.tsx"
        self.assertTrue(page.is_file(), msg=f"missing {page}")
        text = page.read_text(encoding="utf-8")
        self.assertIn("PaperTrading", text)
        # Fabric must not replace the operator page with a stub.
        self.assertGreater(len(text), 500)

    def test_team_collaboration_strategy_still_canonical(self) -> None:
        from Data.modules.cognition.team_strategy import (
            CollaborationStrategy,
            normalize_collaboration_strategy,
        )

        self.assertEqual(normalize_collaboration_strategy("team"), CollaborationStrategy.TEAM)
        self.assertEqual(normalize_collaboration_strategy("TEAM"), CollaborationStrategy.TEAM)
        # Fabric must not invent a second collaboration authority.
        values = {m.value for m in CollaborationStrategy}
        self.assertIn("team", values)

    def test_host_console_liveness_and_cors_surfaces_intact(self) -> None:
        root = Path(__file__).resolve().parents[2] / "modules" / "host_console"
        liveness = root / "liveness.py"
        cors = root / "launcher_cors.py"
        self.assertTrue(liveness.is_file())
        self.assertTrue(cors.is_file())
        self.assertIn("def build_host_liveness", liveness.read_text(encoding="utf-8"))
        cors_text = cors.read_text(encoding="utf-8")
        self.assertTrue(
            "cors" in cors_text.lower() and ("origin" in cors_text.lower() or "CORS" in cors_text),
            msg="launcher CORS surface missing",
        )
        # Prefer runtime import when Starlette deps are present (CI).
        try:
            from Data.modules.host_console.liveness import build_host_liveness

            self.assertTrue(callable(build_host_liveness))
        except ModuleNotFoundError:
            pass


class ExternalFabricClosableGapTests(unittest.TestCase):
    """In-repo DoD gaps closable without LLM / UE5 / Instagram credentials."""

    def test_declared_status_operation_beats_lifecycle_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "status-cli"
            root.mkdir(parents=True)
            tool = Path(tmp) / "status_tool.py"
            tool.write_text(
                "import json\nprint(json.dumps({'marker':'DECLARED_STATUS_OP','ok':True}))\n",
                encoding="utf-8",
            )
            manifest = {
                "module_id": "status-cli",
                "name": "Status CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "operations": [
                            {
                                "name": "status",
                                "command": [sys.executable, str(tool)],
                                "result_format": "json",
                            }
                        ]
                    },
                    "result": {"format": "json"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.status_cli.status",
                        "name": "Status",
                        "external_name": "status",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "status-cli",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            result = manager.execute("status-cli", "status", {})
            self.assertEqual(result.status, "COMPLETED", msg=result.error)
            blob = json.dumps(result.output or {})
            self.assertIn("DECLARED_STATUS_OP", blob)

    def test_http_accept_statuses_allows_202(self) -> None:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # noqa: ANN401
                return

            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                _ = self.rfile.read(n)
                body = b'{"jobId":"job-202","accepted":true}'
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/health"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return
                self.send_response(404)
                self.end_headers()

        port = _free_port()
        server = HTTPServer(("127.0.0.1", port), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "async-http"
                root.mkdir(parents=True)
                manifest = {
                    "module_id": "async-http",
                    "name": "Async HTTP",
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
                                    "name": "generate",
                                    "method": "POST",
                                    "path": "/api/generate",
                                    "body": "json",
                                    "accept_statuses": [200, 201, 202],
                                }
                            ],
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.async_http.generate",
                            "name": "Generate",
                            "external_name": "generate",
                            "side_effects": ["NETWORK"],
                        }
                    ],
                }
                (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
                manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
                manager.discover()
                manager.initialize(
                    "async-http",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                result = manager.execute("async-http", "generate", {"topic": "x"})
                self.assertEqual(result.status, "COMPLETED", msg=result.error)
                meta = ((result.output or {}).get("metadata") or {})
                self.assertEqual(int(meta.get("http_status") or 0), 202)
                structured = (result.output or {}).get("structured_data") or {}
                self.assertEqual(structured.get("jobId"), "job-202")
        finally:
            server.shutdown()

    def test_openmaic_style_job_poll_normalizes_failed_without_llm(self) -> None:
        """202 generate + poll failed/done with 'No model could be resolved' — no LLM keys."""
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # noqa: ANN401
                return

            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                _ = self.rfile.read(n)
                if self.path.startswith("/api/generate-classroom"):
                    body = b'{"jobId":"om-job-1"}'
                    self.send_response(202)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/health") or self.path.startswith("/api/health"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                    return
                if self.path.startswith("/api/generate-classroom/"):
                    body = json.dumps(
                        {
                            "jobId": "om-job-1",
                            "status": "failed",
                            "done": True,
                            "error": "No model could be resolved",
                        }
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        port = _free_port()
        server = HTTPServer(("127.0.0.1", port), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "mods" / "openmaic-mock"
                root.mkdir(parents=True)
                manifest = {
                    "module_id": "openmaic-mock",
                    "name": "OpenMAIC Mock",
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
                                "url": f"http://127.0.0.1:{port}/api/health",
                                "expect_status": 200,
                            },
                            "operations": [
                                {
                                    "name": "generate_course",
                                    "method": "POST",
                                    "path": "/api/generate-classroom",
                                    "body": "json",
                                    "accept_statuses": [200, 201, 202],
                                    "body_aliases": {"topic": "requirement"},
                                },
                                {
                                    "name": "classroom_job_status",
                                    "method": "GET",
                                    "path": "/api/generate-classroom/{jobId}",
                                    "path_params": ["jobId"],
                                },
                            ],
                        },
                        "result": {"format": "json"},
                    },
                    "capabilities": [
                        {
                            "capability_id": "external.openmaic_mock.generate_course",
                            "name": "Generate",
                            "external_name": "generate_course",
                            "side_effects": ["NETWORK"],
                        },
                        {
                            "capability_id": "external.openmaic_mock.classroom_job_status",
                            "name": "Job Status",
                            "external_name": "classroom_job_status",
                            "side_effects": ["READ"],
                        },
                    ],
                }
                (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
                manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
                manager.discover()
                manager.initialize(
                    "openmaic-mock",
                    ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
                )
                created = manager.execute(
                    "openmaic-mock", "generate_course", {"topic": "quant finance"}
                )
                self.assertEqual(created.status, "COMPLETED", msg=created.error)
                job_id = ((created.output or {}).get("structured_data") or {}).get("jobId")
                self.assertEqual(job_id, "om-job-1")
                polled = manager.execute(
                    "openmaic-mock", "classroom_job_status", {"jobId": job_id}
                )
                self.assertEqual(polled.status, "COMPLETED", msg=polled.error)
                structured = (polled.output or {}).get("structured_data") or {}
                self.assertEqual(structured.get("status"), "failed")
                self.assertTrue(structured.get("done"))
                self.assertIn("No model could be resolved", str(structured.get("error") or ""))
        finally:
            server.shutdown()

    def test_optional_module_register_failure_does_not_break_boot_loop(self) -> None:
        """Mirrors main.py: register_external_module_capabilities failures are warnings only."""

        class _Obs:
            def __init__(self) -> None:
                self.events: list[tuple[str, str]] = []

            def emit(self, category: str, name: str, **_: Any) -> None:
                self.events.append((category, name))

        class _Broken:
            class manifest:
                module_id = "broken-ext"
                metadata = {"external": {"adapter": "CLI"}}
                capabilities = ()
                name = "Broken"
                side_effects = ()

        catalog = CapabilityCatalog()
        plugins = PluginRegistry(catalog)
        obs = _Obs()
        ready = [_Broken()]

        def _raise(*_a: Any, **_k: Any) -> list[str]:
            raise RuntimeError("simulated register failure")

        original = register_external_module_capabilities
        try:
            import Data.modules.module_manager.external.catalog_register as cr

            cr.register_external_module_capabilities = _raise  # type: ignore[assignment]
            for managed in ready:
                try:
                    cr.register_external_module_capabilities(
                        catalog=catalog, plugin_registry=plugins, managed=managed
                    )
                except Exception as exc:  # noqa: BLE001
                    obs.emit(
                        "external_capability",
                        "capability_register_failed",
                        payload={"module_id": managed.manifest.module_id, "error": str(exc)},
                        level="warning",
                    )
                else:
                    obs.emit(
                        "external_capability",
                        "external.modules.discovered",
                        payload={"module_id": managed.manifest.module_id},
                    )
        finally:
            cr.register_external_module_capabilities = original  # type: ignore[assignment]

        self.assertIn(("external_capability", "capability_register_failed"), obs.events)
        # Core catalog remains usable.
        register_external_control_capabilities(catalog)
        self.assertIn("external.module.invoke", catalog)
        main_py = Path(__file__).resolve().parents[1] / "main.py"
        text = main_py.read_text(encoding="utf-8")
        self.assertIn("optional modules must not break boot", text)

    def test_executor_emits_external_failures_metric(self) -> None:
        class _CaptureHub:
            def __init__(self) -> None:
                self.events: list[tuple[str, str, dict[str, Any]]] = []

            def emit(self, category: str, name: str, *, payload: dict[str, Any] | None = None, **_: Any) -> None:
                self.events.append((category, name, dict(payload or {})))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mods" / "fail-cli"
            root.mkdir(parents=True)
            tool = Path(tmp) / "fail.py"
            tool.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
            manifest = {
                "module_id": "fail-cli",
                "name": "Fail CLI",
                "version": "0.0.1",
                "entrypoint": FACTORY,
                "external": {
                    "adapter": "CLI",
                    "source_type": "path",
                    "path": str(tmp),
                    "install": {"strategy": "NONE"},
                    "runtime": {
                        "operations": [
                            {
                                "name": "run",
                                "command": [sys.executable, str(tool)],
                                "result_format": "text",
                            }
                        ]
                    },
                    "result": {"format": "TEXT"},
                },
                "capabilities": [
                    {
                        "capability_id": "external.fail_cli.run",
                        "name": "Run",
                        "external_name": "run",
                        "side_effects": ["READ"],
                    }
                ],
            }
            (root / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = ModuleManager(discovery_roots=(Path(tmp) / "mods",), enabled=True)
            manager.discover()
            manager.initialize(
                "fail-cli",
                ModuleContext(database_path=str(Path(tmp) / "c.db"), data_root=tmp),
            )
            hub = _CaptureHub()
            catalog = CapabilityCatalog()
            plugins = PluginRegistry(catalog)
            managed = manager.get("fail-cli")
            assert managed is not None
            register_external_module_capabilities(catalog=catalog, plugin_registry=plugins, managed=managed)
            gateway = ExecutionGateway(
                catalog=catalog,
                module_executor=ExternalModuleExecutor(manager, observability=hub),
            )
            result = gateway.execute(
                CapabilityRequest(
                    capability_id="external.fail_cli.run",
                    arguments={},
                    requested_by="test",
                )
            )
            self.assertNotEqual(result.status.value, "COMPLETED")
            names = [n for _, n, _ in hub.events]
            self.assertIn("external.failures", names, msg=hub.events)
            self.assertIn("external.invocations", names, msg=hub.events)

    def test_matrix_worktree_head_is_recent_git_ancestor(self) -> None:
        """Ledger tip must be a real commit at/behind HEAD (avoids chicken-egg on sync commits)."""
        matrix = Path(__file__).resolve().parent / "external_sources_acceptance_matrix.json"
        data = json.loads(matrix.read_text(encoding="utf-8"))
        recorded = str(data.get("worktree_head") or "").strip()
        self.assertRegex(recorded, r"^[0-9a-f]{40}$")
        repo = str(Path(__file__).resolve().parents[3])
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", recorded, "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if ancestor.returncode == 128:
            self.skipTest("git history unavailable")
        self.assertEqual(ancestor.returncode, 0, msg=f"{recorded} is not an ancestor of HEAD")
        distance = subprocess.run(
            ["git", "rev-list", "--count", f"{recorded}..HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if distance.returncode == 0 and distance.stdout.strip().isdigit():
            self.assertLessEqual(
                int(distance.stdout.strip()),
                25,
                msg=f"worktree_head is {distance.stdout.strip()} commits behind tip; sync the matrix",
            )


if __name__ == "__main__":
    unittest.main()
