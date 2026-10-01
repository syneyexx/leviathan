"""Worker connect/list_tools must durably reconcile MCP catalog (Phase 1.1 / 2)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.mcp import McpBridge, McpProvider, McpStore
from Data.modules.mcp.catalog_sync import McpCatalogSync
from Data.modules.mcp.errors import McpError
from Data.modules.mcp.execution import McpExecutionExecutor
from Data.modules.mcp.limits import McpLimits
from Data.modules.mcp.types import McpSourceKind, McpToolAvailability
from Data.modules.observations import ObservationStore
from Data.modules.plugins import PluginRegistry


FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def _python() -> str:
    return sys.executable


class McpWorkerCatalogReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "control.db"
        self.store = McpStore(self.db)
        self.store.initialize()
        self.job_store = JobStore(self.root / "jobs.db")
        self.job_store.initialize()
        self.runtime = JobRuntime(
            self.job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        self.executor = McpExecutionExecutor(db_path=str(self.db))

    def tearDown(self) -> None:
        self.executor.close()
        self.tmp.cleanup()

    def _register_fake(
        self,
        name: str = "worker-fake",
        *,
        mode: str = "normal",
        extra_args: list[str] | None = None,
        source_kind: str = "manual",
    ):
        args = [str(FAKE_SERVER), f"--mode={mode}"]
        if extra_args:
            args.extend(extra_args)
        bridge = McpBridge(
            store=self.store,
            catalog=build_default_catalog(),
            enabled=True,
            auto_expand_modules=False,
        )
        bridge.initialize()
        return bridge.register_server(
            display_name=name,
            transport="stdio",
            source_kind=source_kind,
            source_key=name,
            command=_python(),
            args=args,
            enabled=True,
            trust="manual",
            semantic_effects={"echo": ["READ"], "add": ["READ"], "echo_0": ["READ"]},
            expand_tools=True,
        )

    def _run_control_job(
        self,
        *,
        capability_id: str,
        server_id: str,
        arguments: dict | None = None,
        worker_id: str = "mcp-worker-1",
    ) -> dict:
        job = self.runtime.enqueue(
            capability_id=capability_id,
            arguments={"server_id": server_id, **dict(arguments or {})},
            worker_pool="mcp_execution",
        )
        claimed = self.job_store.claim_next_queued(
            worker_id=worker_id,
            worker_pool="mcp_execution",
            lease_ttl_seconds=60.0,
            capability_ids={capability_id},
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        ctx = {
            "job_store": self.job_store,
            "worker_id": worker_id,
            "lease_ttl_seconds": 60.0,
        }
        result = self.executor.execute_job(ctx, claimed)
        return result

    def _build_gateway(self, catalog, bridge: McpBridge) -> ExecutionGateway:
        artifacts = ArtifactStore(self.db, self.root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(
            self.db, data_root=self.root / "corp", chunk_max_chars=200, chunk_overlap=20
        )
        knowledge.initialize()
        (self.root / "corp").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="K", content="needle", source="t")
        fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(self.db)
        obs.initialize()
        return ExecutionGateway(
            catalog=catalog,
            function_runtime=fn,
            knowledge_retriever=HybridRetriever(knowledge),
            knowledge_store=knowledge,
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
            mcp_executor=McpProvider(bridge),
        )

    def test_list_tools_persists_schemas_hashes_and_bumps_generation(self) -> None:
        cfg = self._register_fake("persist")
        before = self.store.get_catalog_generation(cfg.server_id)
        out = self._run_control_job(
            capability_id="mcp.list_tools",
            server_id=cfg.server_id,
            arguments={"force_refresh": True, "expand_tools": True},
        )
        self.assertEqual(out.get("status"), "succeeded")
        self.assertTrue(out.get("reconciled"))
        self.assertGreater(int(out.get("catalog_generation") or 0), before)

        tools = self.store.list_tools(server_id=cfg.server_id)
        names = {t.external_name for t in tools}
        self.assertIn("echo", names)
        self.assertIn("add", names)
        for tool in tools:
            if tool.availability != McpToolAvailability.AVAILABLE:
                continue
            self.assertTrue(tool.schema_hash)
            self.assertIsInstance(tool.input_schema, dict)
            self.assertEqual(tool.availability, McpToolAvailability.AVAILABLE)

        durable_gen = self.store.get_catalog_generation(cfg.server_id)
        self.assertEqual(int(out["catalog_generation"]), durable_gen)

    def test_hydrate_into_catalog_and_gateway_visibility(self) -> None:
        cfg = self._register_fake("hydrate")
        out = self._run_control_job(
            capability_id="mcp.connect",
            server_id=cfg.server_id,
            arguments={"expand_tools": True},
        )
        self.assertEqual(out.get("status"), "succeeded")
        self.assertTrue(out.get("reconciled"))

        # Fresh API-process catalog — empty until hydrate from durable store.
        catalog = build_default_catalog()
        plugins = PluginRegistry(catalog)
        sync = McpCatalogSync(catalog=catalog, store=self.store, plugin_registry=plugins)
        projected = sync.project_server_into_catalog(cfg.server_id)
        self.assertGreaterEqual(len(projected), 2)

        echo = next(t for t in projected if t.external_name == "echo")
        cap = catalog.get(echo.capability_id)
        self.assertIsNotNone(cap)
        assert cap is not None
        self.assertEqual(cap.provider_kind, CapabilityProviderKind.MCP)
        self.assertTrue(cap.available)

        bridge = McpBridge(
            store=self.store,
            catalog=catalog,
            plugin_registry=plugins,
            enabled=True,
            auto_expand_modules=False,
        )
        # Do not call initialize() — that would mark tools unavailable.
        bridge.reconcile_catalog_from_store(cfg.server_id)
        gateway = self._build_gateway(catalog, bridge)
        # Capability must be visible to the gateway catalog (canonical registry).
        self.assertIsNotNone(gateway.get_capability(echo.capability_id))
        known = catalog.get(echo.capability_id)
        self.assertIsNotNone(known)
        assert known is not None
        self.assertTrue(known.available)
        self.assertEqual(known.provider_kind, CapabilityProviderKind.MCP)
        # Without a live session, invoke may fail/reject — but not as unknown.
        result = gateway.execute(
            CapabilityRequest(capability_id=echo.capability_id, arguments={"text": "hi"})
        )
        self.assertIn(
            result.status,
            {
                CapabilityStatus.COMPLETED,
                CapabilityStatus.FAILED,
                CapabilityStatus.REJECTED,
            },
        )
        if result.status == CapabilityStatus.REJECTED:
            self.assertNotIn("unknown", (result.error or "").lower())

    def test_zero_tools_marks_unavailable_and_clears_bindings(self) -> None:
        cfg = self._register_fake("zero-seed")
        # First reconcile with real tools.
        first = self._run_control_job(
            capability_id="mcp.list_tools",
            server_id=cfg.server_id,
        )
        self.assertEqual(first.get("status"), "succeeded")
        seeded = self.store.list_tools(server_id=cfg.server_id)
        self.assertTrue(any(t.availability == McpToolAvailability.AVAILABLE for t in seeded))

        catalog = build_default_catalog()
        plugins = PluginRegistry(catalog)
        sync = McpCatalogSync(catalog=catalog, store=self.store, plugin_registry=plugins)
        sync.project_server_into_catalog(cfg.server_id)
        plugin_id = f"mcp:{cfg.server_id}"
        self.assertIsNotNone(plugins.get(plugin_id))

        # Zero-tool sync clears availability + plugin bindings.
        empty_sync = McpCatalogSync(catalog=catalog, store=self.store, plugin_registry=plugins)
        empty_sync.sync_tools(
            self.store.get_server(cfg.server_id),  # type: ignore[arg-type]
            [],
            protocol_version="2024-11-05",
            server_version="1.0.0",
            available=True,
        )
        after = self.store.list_tools(server_id=cfg.server_id)
        self.assertTrue(after)
        self.assertTrue(all(t.availability == McpToolAvailability.UNAVAILABLE for t in after))
        plugin = plugins.get(plugin_id)
        self.assertTrue(plugin is None or len(plugin.bindings) == 0 or plugin.status.value == "disabled")

    def test_failed_sync_does_not_report_success(self) -> None:
        cfg = self._register_fake("fail-sync")
        with mock.patch(
            "Data.modules.mcp.catalog_sync.McpCatalogSync.sync_tools",
            side_effect=RuntimeError("reconcile boom"),
        ):
            out = self._run_control_job(
                capability_id="mcp.list_tools",
                server_id=cfg.server_id,
                arguments={"expand_tools": True},
            )
        self.assertEqual(out.get("status"), "failed")
        self.assertFalse(out.get("reconciled", True))
        self.assertEqual((out.get("error") or {}).get("code"), "MCP_CATALOG_RECONCILE_FAILED")
        # Confirm job was not left COMPLETED.
        jobs = self.job_store.list(limit=20)
        matching = [j for j in jobs if j.capability_id == "mcp.list_tools"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].state, JobState.FAILED)

    def test_invalid_schema_records_sync_issue_without_poisoning_siblings(self) -> None:
        cfg = self._register_fake("issues")
        catalog = build_default_catalog()
        sync = McpCatalogSync(catalog=catalog, store=self.store, plugin_registry=None)
        config = self.store.get_server(cfg.server_id)
        assert config is not None
        records = sync.sync_tools(
            config,
            [
                {
                    "name": "good",
                    "description": "ok",
                    "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
                },
                {"description": "missing name"},
                {
                    "name": "bad_schema",
                    "description": "nope",
                    "inputSchema": ["not", "an", "object"],
                },
            ],
            protocol_version="2024-11-05",
            server_version="1.0.0",
            available=True,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].external_name, "good")
        self.assertGreaterEqual(len(sync.sync_issues), 2)
        codes = {i["error_code"] for i in sync.sync_issues}
        self.assertIn("MCP_TOOL_SCHEMA_INVALID", codes)
        durable = self.store.list_sync_issues(cfg.server_id)
        self.assertGreaterEqual(len(durable), 2)
        self.assertIsNotNone(catalog.get(records[0].capability_id))

    def test_config_owned_unregister_requires_force(self) -> None:
        cfg = self._register_fake("cfg-owned", source_kind="config")
        self.assertEqual(cfg.source_kind, McpSourceKind.CONFIG)
        catalog = build_default_catalog()
        bridge = McpBridge(store=self.store, catalog=catalog, enabled=True)
        bridge.initialize()
        with self.assertRaises(McpError) as ctx:
            bridge.unregister_server(cfg.server_id)
        self.assertEqual(ctx.exception.code, "MCP_SERVER_CONFLICT")
        bridge.unregister_server(cfg.server_id, force=True)
        self.assertIsNone(self.store.get_server(cfg.server_id))

    def test_bridge_reconcile_if_stale_after_worker_generation_bump(self) -> None:
        cfg = self._register_fake("stale")
        catalog = build_default_catalog()
        plugins = PluginRegistry(catalog)
        bridge = McpBridge(
            store=self.store,
            catalog=catalog,
            plugin_registry=plugins,
            enabled=True,
            auto_expand_modules=False,
        )
        # Track generation 0 without projecting available tools.
        bridge._projected_generations[cfg.server_id] = 0

        out = self._run_control_job(
            capability_id="mcp.list_tools",
            server_id=cfg.server_id,
        )
        self.assertTrue(out.get("reconciled"))
        self.assertGreater(int(out["catalog_generation"]), 0)

        result = bridge.reconcile_if_stale(cfg.server_id)
        self.assertIsNotNone(result)
        tools = bridge.list_tools(server_id=cfg.server_id)
        self.assertTrue(any(t.availability == McpToolAvailability.AVAILABLE for t in tools))
        # Second call should be a no-op once projected.
        self.assertIsNone(bridge.reconcile_if_stale(cfg.server_id))


if __name__ == "__main__":
    unittest.main()
