from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.agents import AgentKind, AgentRuntime, MultiAgentCoordinator
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.native import NativeRuntimeStub
from Data.modules.observations import ObservationStore
from Data.modules.security import SecurityAuditor, SecurityFinding
from Data.modules.trading import TradingStub


class MultiAgentAndDepthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "m.db"
        artifacts = ArtifactStore(db, root / "a")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="M", content="multi agent research needle", source="t")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(db)
        obs.initialize()
        gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        self.agents = AgentRuntime(gateway=gateway, agents_enabled=True)
        self.multi = MultiAgentCoordinator(self.agents)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_coding_plan_includes_verify(self) -> None:
        steps = self.agents.plan("read file and inspect csv", kind=AgentKind.CODING)
        kinds = [s.kind.value for s in steps]
        self.assertIn("VERIFY", kinds)
        # Coding planner routes file work through allowlisted capabilities.
        self.assertTrue(
            any(s.capability_id in {"file.read", "file.inspect_csv", "workspace.list"} for s in steps),
            msg=[(s.kind.value, s.capability_id) for s in steps],
        )

    def test_multi_agent_runs_sequence(self) -> None:
        result = self.multi.run("search multi agent research", kinds=[AgentKind.RESEARCH, AgentKind.GENERIC])
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(len(result.results), 2)
        self.assertTrue(result.public_dict()["truth"]["multi_agent_still_uses_shared_gateway"])


class SecurityNativeTradingTests(unittest.TestCase):
    def test_security_auditor(self) -> None:
        auditor = SecurityAuditor(
            checks=[
                lambda: SecurityFinding("a", "info", "t", "d", True),
                lambda: SecurityFinding("b", "high", "t2", "d2", False),
            ]
        )
        report = auditor.run()
        self.assertEqual(report.summary["failed"], 1)
        self.assertTrue(report.public_dict()["truth"]["audit_report_is_not_penetration_test"])

    def test_native_unavailable(self) -> None:
        probe = NativeRuntimeStub().probe()
        self.assertFalse(probe.available)

    def test_trading_refused(self) -> None:
        result = TradingStub().place_order(symbol="ABC", side="buy", quantity=1)
        self.assertFalse(result.accepted)


if __name__ == "__main__":
    unittest.main()
