from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.agents import AgentKind, AgentRuntime
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "a.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "corpus", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "corpus").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(
            title="Agent Doc",
            content="leviathan agent gateway search target",
            source="test",
        )
        fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(db)
        obs.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        self.fn = fn
        self.disabled = AgentRuntime(gateway=self.gateway, agents_enabled=False)
        self.enabled = AgentRuntime(gateway=self.gateway, agents_enabled=True)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_disabled_without_feature_flag(self) -> None:
        result = self.disabled.execute("search something")
        self.assertEqual(result.status, "DISABLED")

    def test_research_plan_uses_knowledge_capability(self) -> None:
        result = self.enabled.execute("search leviathan agent", kind=AgentKind.RESEARCH)
        self.assertEqual(result.status, "COMPLETED")
        self.assertTrue(result.public_dict()["truth"]["agents_use_shared_gateway"])
        caps = [s for s in result.steps if s.get("capability_id") == "knowledge.search"]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
