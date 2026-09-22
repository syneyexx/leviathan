"""Universal MCP bridge — deterministic protocol, gateway, multi-server, security tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import (
    CapabilityProviderKind,
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.function_runtime.types import SideEffect as SE
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.mcp import (
    McpBridge,
    McpProvider,
    McpStore,
    register_module_mcp,
    unregister_module_mcp,
)
from Data.modules.mcp.errors import McpError
from Data.modules.mcp.limits import McpLimits
from Data.modules.observations import ObservationStore
from Data.modules.plugins import PluginRegistry


FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def _python() -> str:
    return sys.executable


class McpBridgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "mcp.db"
        self.store = McpStore(self.db)
        self.store.initialize()
        self.catalog = build_default_catalog()
        self.plugins = PluginRegistry(self.catalog)
        self.bridge = McpBridge(
            store=self.store,
            catalog=self.catalog,
            plugin_registry=self.plugins,
            enabled=True,
            stdio_enabled=True,
            http_enabled=True,
            auto_expand_modules=False,
            allow_outbound=False,
            limits=McpLimits(
                max_restart_attempts=3,
                restart_window_seconds=60.0,
                circuit_open_seconds=1.0,
                startup_timeout_seconds=10.0,
            ),
            secret_overrides={"secret:test_token": "SUPER_SECRET_VALUE_XYZ"},
        )
        self.bridge.initialize()
        artifacts = ArtifactStore(self.db, self.root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(
            self.db, data_root=self.root / "corp", chunk_max_chars=200, chunk_overlap=20
        )
        knowledge.initialize()
        (self.root / "corp").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="K", content="needle", source="t")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.obs = ObservationStore(self.db)
        self.obs.initialize()
        self.provider = McpProvider(self.bridge)
        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            knowledge_store=knowledge,
            artifact_store=artifacts,
            approval_checker=self.approvals,
            observation_store=self.obs,
            mcp_executor=self.provider,
        )

    def tearDown(self) -> None:
        self.bridge.shutdown()
        self.fn.shutdown()
        self.tmp.cleanup()

    def _register_fake(
        self,
        name: str = "fake",
        *,
        mode: str = "normal",
        enabled: bool = True,
        trust: str = "manual",
        semantic_effects: dict | None = None,
        requested_isolation: str = "subprocess",
        extra_args: list[str] | None = None,
        secret_refs: dict | None = None,
        env: dict | None = None,
    ):
        args = [str(FAKE_SERVER), f"--mode={mode}"]
        if extra_args:
            args.extend(extra_args)
        return self.bridge.register_server(
            display_name=name,
            transport="stdio",
            source_kind="manual",
            source_key=name,
            command=_python(),
            args=args,
            enabled=enabled,
            trust=trust,
            semantic_effects=semantic_effects
            or {
                "echo": ["READ"],
                "add": ["READ"],
                "echo_0": ["READ"],
            },
            requested_isolation=requested_isolation,
            secret_refs=secret_refs or {},
            env=env or {},
            expand_tools=True,
        )

    def test_stdio_initialize_list_call(self) -> None:
        cfg = self._register_fake("proto")
        runtime = self.bridge.connect(cfg.server_id)
        self.assertEqual(runtime.state.value, "READY")
        self.assertIsNotNone(runtime.protocol_version)
        tools = self.bridge.list_tools(server_id=cfg.server_id)
        names = {t.external_name for t in tools}
        self.assertIn("echo", names)
        self.assertIn("add", names)
        for tool in tools:
            self.assertTrue(tool.capability_id.startswith("mcp."))
            self.assertEqual(tool.availability.value, "available")
            cap = self.catalog.get(tool.capability_id)
            self.assertIsNotNone(cap)
            assert cap is not None
            self.assertEqual(cap.provider_kind, CapabilityProviderKind.MCP)
            self.assertTrue(cap.available)

        result = self.bridge.call_tool(cfg.server_id, "echo", {"text": "hello"})
        self.assertEqual(result.status.value, "COMPLETED")
        self.assertEqual(result.content[0]["text"], "hello")

    def test_concurrent_calls_demultiplex(self) -> None:
        cfg = self._register_fake("multi")
        self.bridge.connect(cfg.server_id)
        results: list = []

        def worker(i: int) -> None:
            results.append(self.bridge.call_tool(cfg.server_id, "add", {"a": i, "b": 1}))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.status.value == "COMPLETED" for r in results))

    def test_disconnect_marks_unavailable_preserves_identity(self) -> None:
        cfg = self._register_fake("disc")
        self.bridge.connect(cfg.server_id)
        tools = self.bridge.list_tools(server_id=cfg.server_id)
        cap_id = tools[0].capability_id
        self.bridge.disconnect(cfg.server_id)
        tools2 = self.bridge.list_tools(server_id=cfg.server_id)
        self.assertEqual(len(tools2), len(tools))
        self.assertTrue(all(t.availability.value == "unavailable" for t in tools2))
        cap = self.catalog.get(cap_id)
        self.assertIsNotNone(cap)
        assert cap is not None
        self.assertFalse(cap.available)
        self.assertEqual(cap.availability_reason, "server_offline")

    def test_schema_hash_change_detected(self) -> None:
        cfg = self._register_fake("hash")
        self.bridge.connect(cfg.server_id)
        tool = self.bridge.list_tools(server_id=cfg.server_id)[0]
        old_hash = tool.schema_hash
        # Mutate stored schema then refresh should update hash when server schema same —
        # force event by upserting different hash then refresh.
        from Data.modules.mcp.types import McpToolAvailability, McpToolRecord

        mutated = McpToolRecord(
            server_id=tool.server_id,
            external_name=tool.external_name,
            capability_id=tool.capability_id,
            description=tool.description,
            input_schema={"type": "object", "properties": {"changed": {"type": "string"}}},
            schema_hash="deadbeef",
            semantic_effects=tool.semantic_effects,
            availability=McpToolAvailability.AVAILABLE,
            first_seen_at=tool.first_seen_at,
            last_seen_at=tool.last_seen_at,
        )
        self.store.upsert_tool(mutated)
        before = len(self.bridge.sync.schema_change_events)
        self.bridge.refresh_tools(cfg.server_id)
        self.assertGreater(len(self.bridge.sync.schema_change_events), before)
        refreshed = self.store.get_tool(tool.capability_id)
        assert refreshed is not None
        self.assertNotEqual(refreshed.schema_hash, "deadbeef")
        self.assertEqual(refreshed.schema_hash, old_hash)

    def test_gateway_blocks_without_approval(self) -> None:
        cfg = self._register_fake(
            "gated",
            semantic_effects={"echo": ["WRITE"], "add": ["WRITE"]},
            trust="untrusted",
        )
        self.bridge.connect(cfg.server_id)
        self.bridge.refresh_tools(cfg.server_id)
        echo = next(
            t for t in self.bridge.list_tools(server_id=cfg.server_id) if t.external_name == "echo"
        )
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=echo.capability_id,
                arguments={"text": "x", "approved_by_user": True},
            )
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertIn("approval", (result.error or "").lower())

    def test_gateway_honors_real_approval(self) -> None:
        cfg = self._register_fake(
            "approved",
            semantic_effects={"echo": ["WRITE"], "add": ["READ"]},
        )
        self.bridge.connect(cfg.server_id)
        self.bridge.refresh_tools(cfg.server_id)
        echo = next(t for t in self.bridge.list_tools(server_id=cfg.server_id) if t.external_name == "echo")
        approval = self.approvals.request(
            capability_id=echo.capability_id,
            side_effects=(SE.WRITE,),
            requested_by="test",
        )
        self.approvals.approve(approval.approval_id, decided_by="operator")
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id=echo.capability_id,
                arguments={"text": "ok"},
                approval_id=approval.approval_id,
            )
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertTrue(result.output["truth"]["mcp_output_is_observation_not_evidence"])

    def test_manual_api_path_uses_gateway_semantics(self) -> None:
        """Provider only reachable after gateway policy — unavailable blocked."""
        cfg = self._register_fake("api")
        self.bridge.connect(cfg.server_id)
        tool = self.bridge.list_tools(server_id=cfg.server_id)[0]
        self.bridge.disconnect(cfg.server_id)
        result = self.gateway.execute(
            CapabilityRequest(capability_id=tool.capability_id, arguments={"text": "x"})
        )
        self.assertEqual(result.status, CapabilityStatus.REJECTED)
        self.assertEqual(result.telemetry.get("reason"), "unavailable")

    def test_multi_server_isolation(self) -> None:
        configs = [self._register_fake(f"s{i}") for i in range(5)]
        for cfg in configs:
            self.bridge.connect(cfg.server_id)
        # Kill one — others remain
        self.bridge.disconnect(configs[0].server_id)
        for cfg in configs[1:]:
            health = self.bridge.server_health(cfg.server_id)
            self.assertIn(health.state.value, {"READY", "BUSY", "DEGRADED"})
            result = self.bridge.call_tool(cfg.server_id, "echo", {"text": "ok"})
            self.assertEqual(result.status.value, "COMPLETED")

    def test_circuit_breaker(self) -> None:
        cfg = self.bridge.register_server(
            display_name="circuit",
            transport="stdio",
            source_kind="manual",
            source_key="circuit",
            command=_python(),
            args=["-c", "import sys; sys.exit(1)"],
            enabled=True,
            trust="manual",
            expand_tools=False,
        )
        failures = 0
        for _ in range(5):
            try:
                self.bridge.connect(cfg.server_id)
            except McpError:
                failures += 1
        self.assertGreaterEqual(failures, 3)
        with self.bridge._lock:
            session = self.bridge._sessions.get(cfg.server_id)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertTrue(session.runtime.circuit_open)
        with self.assertRaises(McpError) as ctx:
            self.bridge.connect(cfg.server_id)
        self.assertEqual(ctx.exception.code, "MCP_CIRCUIT_OPEN")

    def test_oversized_tool_count_limit(self) -> None:
        self.bridge.limits = McpLimits(max_tools_per_server=3)
        cfg = self.bridge.register_server(
            display_name="flood",
            transport="stdio",
            source_kind="manual",
            source_key="flood",
            command=_python(),
            args=[str(FAKE_SERVER), "--mode=many_tools", "--tool-count=20"],
            enabled=True,
            trust="manual",
            expand_tools=False,
            semantic_effects={"echo_0": ["READ"]},
        )
        # Patch session limits after connect
        runtime = self.bridge.connect(cfg.server_id)
        self.assertEqual(runtime.state.value, "READY")
        with self.bridge._lock:
            session = self.bridge._sessions[cfg.server_id]
            session.limits = McpLimits(max_tools_per_server=3)
        with self.assertRaises(McpError) as ctx:
            self.bridge.refresh_tools(cfg.server_id)
        self.assertEqual(ctx.exception.code, "MCP_PROTOCOL_LIMIT_EXCEEDED")

    def test_secrets_not_in_public_or_history(self) -> None:
        cfg = self._register_fake(
            "sec",
            secret_refs={"TOKEN": "secret:test_token"},
            env={"LOG_LEVEL": "info"},
        )
        public = self.bridge.get_server_public(cfg.server_id)
        blob = json.dumps(public)
        self.assertNotIn("SUPER_SECRET_VALUE_XYZ", blob)
        self.assertIn("secret:test_token", blob)
        self.bridge.connect(cfg.server_id)
        self.bridge.call_tool(cfg.server_id, "echo", {"text": "hi"})
        calls = self.bridge.list_calls(server_id=cfg.server_id)
        self.assertTrue(calls)
        call_blob = json.dumps(calls[0].public_dict())
        self.assertNotIn("SUPER_SECRET_VALUE_XYZ", call_blob)

    def test_isolation_honesty_fail_closed(self) -> None:
        cfg = self._register_fake("iso", requested_isolation="container")
        with self.assertRaises(McpError) as ctx:
            self.bridge.connect(cfg.server_id)
        self.assertEqual(ctx.exception.code, "MCP_ISOLATION_UNAVAILABLE")
        public = self.bridge.get_server_public(cfg.server_id)
        self.assertEqual(public["requested_isolation"], "container")
        # effective must not claim container
        self.assertNotEqual(public["runtime"].get("effective_isolation"), "container")

    def test_sse_unsupported(self) -> None:
        with self.assertRaises(McpError) as ctx:
            self.bridge.register_server(
                display_name="sse",
                transport="sse",
                url="http://127.0.0.1:9/sse",
            )
        self.assertEqual(ctx.exception.code, "MCP_TRANSPORT_UNSUPPORTED")

    def test_feature_off_bridge(self) -> None:
        off = McpBridge(
            store=McpStore(self.root / "off.db"),
            catalog=build_default_catalog(),
            enabled=False,
        )
        off.initialize()
        with self.assertRaises(McpError) as ctx:
            off.register_server(display_name="x", transport="stdio", command="true")
        self.assertEqual(ctx.exception.code, "MCP_FEATURE_DISABLED")
        summary = off.health_summary()
        self.assertFalse(summary.feature_enabled)

    def test_module_integration_ownership(self) -> None:
        mod_dir = self.root / "mod_mcp"
        mod_dir.mkdir()
        # Minimal ILeviathanModule via echo pattern — only need module.json for MCP registration
        (mod_dir / "module.json").write_text(
            json.dumps(
                {
                    "module_id": "test.mcp_mod",
                    "name": "MCP Mod",
                    "version": "0.0.1",
                    "entrypoint": "Data.modules.neuro.echo_module:create_echo_module",
                    "capabilities": [],
                    "mcp": {
                        "default_trust": "manual",
                        "expand_tools": True,
                        "servers": [
                            {
                                "name": "mod-fake",
                                "transport": "stdio",
                                "command": _python(),
                                "args": [str(FAKE_SERVER), "--mode=normal"],
                                "enabled": True,
                                "semantic_effects": {"echo": ["READ"], "add": ["READ"]},
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.bridge.auto_expand_modules = True
        registered = register_module_mcp(
            self.bridge,
            module_id="test.mcp_mod",
            manifest_path=str(mod_dir / "module.json"),
        )
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0].owner_module_id, "test.mcp_mod")
        # Manual server should survive module unload
        manual = self._register_fake("keep-me")
        removed = unregister_module_mcp(self.bridge, "test.mcp_mod")
        self.assertEqual(removed, 1)
        self.assertIsNone(self.store.get_server(registered[0].server_id))
        self.assertIsNotNone(self.store.get_server(manual.server_id))

    def test_capability_search_shortlist(self) -> None:
        cfg = self._register_fake("searchme")
        self.bridge.connect(cfg.server_id)
        hits = self.catalog.search("echo", limit=10)
        self.assertTrue(any(h.provider_kind == CapabilityProviderKind.MCP for h in hits))
        # Search returns shortlist objects without requiring dumping every schema into prompts
        inspected = self.catalog.inspect(hits[0].id)
        self.assertIsNotNone(inspected)
        assert inspected is not None
        self.assertIn("input_schema", inspected)

    def test_timeout(self) -> None:
        from Data.modules.mcp.types import McpToolAvailability, McpToolRecord, mcp_capability_id, stable_schema_hash
        from Data.modules.mcp.store import utc_now

        cfg = self.bridge.register_server(
            display_name="slow",
            transport="stdio",
            source_kind="manual",
            source_key="slow",
            command=_python(),
            args=[str(FAKE_SERVER), "--mode=slow", "--delay=3"],
            enabled=True,
            trust="manual",
            timeout_seconds=0.4,
            expand_tools=False,
            semantic_effects={"echo": ["READ"], "add": ["READ"]},
        )
        self.bridge.connect(cfg.server_id)
        cap_id = mcp_capability_id(cfg.server_id, "echo")
        now = utc_now()
        self.store.upsert_tool(
            McpToolRecord(
                server_id=cfg.server_id,
                external_name="echo",
                capability_id=cap_id,
                description="echo",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                schema_hash=stable_schema_hash({"type": "object"}),
                semantic_effects=("READ",),
                availability=McpToolAvailability.AVAILABLE,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        result = self.bridge.call_tool(cfg.server_id, "echo", {"text": "x"})
        self.assertEqual(result.status.value, "TIMEOUT")


class McpFeatureFlagConfigTests(unittest.TestCase):
    def test_child_requires_parent(self) -> None:
        from Data.backend.config import ConfigurationError, Settings

        env = {
            "LEVIATHAN_FEATURE_MCP": "false",
            "LEVIATHAN_FEATURE_MCP_STDIO": "true",
        }
        # from_env coerces children to false when parent false — should not raise
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            # Need to clear cached settings? Settings.from_env reads env fresh.
            cfg = Settings.from_env()
            self.assertFalse(cfg.features.mcp_enabled)
            self.assertFalse(cfg.features.mcp_stdio)


if __name__ == "__main__":
    unittest.main()
