from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.modules.plugins import PluginRegistry, PluginStatus


class PluginRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "p.db"
        artifacts = ArtifactStore(db, root / "a")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="P", content="plugin search needle", source="t")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(db)
        obs.initialize()
        self.catalog = build_default_catalog()
        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        self.registry = PluginRegistry(self.catalog)
        self.registry.register_echo_mcp_stub()

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_mcp_stub_resolves_and_executes_via_gateway(self) -> None:
        plugin = self.registry.get("mcp-echo-stub")
        assert plugin is not None
        self.assertEqual(plugin.status, PluginStatus.ENABLED)
        cap = self.registry.resolve_capability("mcp-echo-stub", "search")
        self.assertEqual(cap, "plugin.echo_search")
        result = self.gateway.execute(
            CapabilityRequest(capability_id=cap, arguments={"query": "plugin search", "limit": 3})
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertTrue(plugin.public_dict()["truth"]["discoverable_capability_is_not_authorized_capability"])

    def test_disabled_plugin_does_not_resolve(self) -> None:
        self.registry.set_status("mcp-echo-stub", PluginStatus.DISABLED)
        self.assertIsNone(self.registry.resolve_capability("mcp-echo-stub", "search"))


if __name__ == "__main__":
    unittest.main()
