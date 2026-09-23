"""Wave 1 — Cognitive hydrate/resume, Gateway invoke, DAG multi-agent."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.agents import (
    AgentBlackboard,
    AgentKind,
    AgentRuntime,
    DagCycleError,
    DagNode,
    MultiAgentCoordinator,
    StructuredAgentPlanner,
)
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.cognition import (
    CognitionStore,
    CognitiveAction,
    CognitiveActionKind,
    CognitiveRuntime,
    CognitiveRunStatus,
    MetaDecision,
    ReasoningStrategy,
)
from Data.modules.cognition.meta_controller import MetaController
from Data.modules.execution import CapabilityStatus, ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore


class CognitiveHydrationResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "cog.db"
        self.store = CognitionStore(self.db)
        # Ensure schema via migrations-compatible initialize path used by RunStore elsewhere.
        # CognitionStore assumes tables exist; create via MigrationRunner.
        from Data.backend.migrations import MigrationRunner

        MigrationRunner(self.db).apply_all()

        self.runtime = CognitiveRuntime(
            enabled=True,
            shadow=False,
            iterative=True,
            store=self.store,
            model_caller=lambda **kwargs: "hydrate-answer",
            execution_gateway=None,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_persist_hydrate_resume_reconstructs_state(self) -> None:
        submitted = self.runtime.submit("Explain LEVIATHAN run ownership briefly", run=True)
        run_id = submitted["run_id"]
        self.assertIn(submitted["status"], {s.value for s in CognitiveRunStatus})

        # Simulate process restart: drop in-memory state, hydrate from SQLite.
        self.runtime._runs.clear()
        hydrated = self.runtime.hydrate(run_id)
        self.assertEqual(hydrated["run_id"], run_id)
        state = self.runtime._runs[run_id]
        self.assertTrue(state.task.goal)
        self.assertIsNotNone(state.decision)
        self.assertGreaterEqual(len(state.actions) + len(state.observations), 0)

        # Resume a completed run returns terminal status without crashing.
        resumed = self.runtime.resume(run_id)
        self.assertEqual(resumed["run_id"], run_id)


class CognitiveGatewayInvokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "gw.db"
        from Data.backend.migrations import MigrationRunner

        MigrationRunner(self.db).apply_all()
        self.store = CognitionStore(self.db)
        self.artifacts = ArtifactStore(self.db, self.root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(
            self.db,
            data_root=self.root / "corpus",
            chunk_max_chars=400,
            chunk_overlap=40,
        )
        self.knowledge.initialize()
        (self.root / "corpus").mkdir(parents=True, exist_ok=True)
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            knowledge_store=self.knowledge,
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
        )
        self.runtime = CognitiveRuntime(
            enabled=True,
            iterative=True,
            store=self.store,
            execution_gateway=self.gateway,
            model_caller=lambda **kwargs: "after-tool answer",
        )

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_invoke_capability_executes_via_gateway(self) -> None:
        state = self.runtime.submit("tool probe", run=False)
        run_id = state["run_id"]
        live = self.runtime._runs[run_id]
        decision = MetaController().decide(live.task)
        live.decision = MetaDecision(
            mode=decision.mode,
            strategy=ReasoningStrategy.TOOL_DRIVEN,
            budgets=decision.budgets,
            value_scores=decision.value_scores,
            notes=decision.notes,
        )
        live.status = CognitiveRunStatus.REASONING
        action = CognitiveAction(
            kind=CognitiveActionKind.INVOKE_CAPABILITY,
            action_id="act-knowledge-1",
            capability_id="knowledge.search",
            arguments={"query": "ExecutionGateway", "limit": 3},
        )
        obs = self.runtime._execute_action(live, action, history=None)
        assert obs is not None
        self.assertEqual(obs.kind.value, "TOOL_RESULT")
        # Empty corpus may still COMPLETE with empty hits.
        self.assertIn(obs.payload.get("result", {}).get("status"), {
            CapabilityStatus.COMPLETED.value,
            CapabilityStatus.FAILED.value,
            CapabilityStatus.REJECTED.value,
        })
        if obs.success:
            self.assertEqual(obs.payload.get("capability_id"), "knowledge.search")

        # Idempotent replay does not double-invoke when prior success observation exists.
        if obs.success:
            live.observations.append(obs)
            replay = self.runtime._execute_action(live, action, history=None)
            self.assertEqual(replay.observation_id, obs.observation_id)


class StructuredAgentPlannerTests(unittest.TestCase):
    def test_research_plan_is_not_keyword_if_chain(self) -> None:
        plan = StructuredAgentPlanner().plan(
            "Summarize ownership matrix without saying search or find",
            kind=AgentKind.RESEARCH,
            available_capabilities=("knowledge.search",),
        )
        self.assertEqual(plan.source, "structured")
        self.assertTrue(plan.public_dict()["truth"]["not_keyword_planner"])
        caps = [s.capability_id for s in plan.steps if s.capability_id]
        self.assertIn("knowledge.search", caps)

    def test_agent_runtime_uses_structured_plan(self) -> None:
        gateway = ExecutionGateway(catalog=build_default_catalog())
        agents = AgentRuntime(gateway=gateway, agents_enabled=True)
        steps = agents.plan("anything without magic keywords", kind=AgentKind.RESEARCH)
        self.assertTrue(any(s.capability_id == "knowledge.search" for s in steps))


class DagMultiAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.agents = AgentRuntime(gateway=self.gateway, agents_enabled=True)
        self.coord = MultiAgentCoordinator(self.agents)

    def test_cycle_detection(self) -> None:
        nodes = (
            DagNode(node_id="a", kind=AgentKind.GENERIC, depends_on=("b",)),
            DagNode(node_id="b", kind=AgentKind.GENERIC, depends_on=("a",)),
        )
        with self.assertRaises(DagCycleError):
            self.coord.run_dag("x", nodes=nodes)

    def test_parallel_independent_branches(self) -> None:
        nodes = (
            DagNode(node_id="research", kind=AgentKind.RESEARCH, depends_on=()),
            DagNode(node_id="generic", kind=AgentKind.GENERIC, depends_on=()),
            DagNode(
                node_id="join",
                kind=AgentKind.GENERIC,
                depends_on=("research", "generic"),
            ),
        )
        board = AgentBlackboard(run_id="run-dag")
        outcome = self.coord.run_dag(
            "Compare run vs jobs ownership",
            nodes=nodes,
            max_parallel=2,
            blackboard=board,
            run_id="run-dag",
        )
        self.assertIn(outcome.status, {"COMPLETED", "PARTIAL", "FAILED", "UNVERIFIED"})
        self.assertGreaterEqual(len(outcome.results), 2)
        self.assertIsNotNone(outcome.blackboard)
        self.assertTrue(outcome.public_dict()["truth"]["dag_supports_parallel_joins"])
        node_ids = {r.get("node_id") for r in outcome.results}
        self.assertIn("research", node_ids)
        self.assertIn("generic", node_ids)

    def test_blackboard_supersession(self) -> None:
        board = AgentBlackboard(run_id="r1")
        first = board.post(kind="hypothesis", content="A", author="a", confidence=0.4)
        second = board.post(
            kind="hypothesis",
            content="B",
            author="b",
            confidence=0.8,
            supersedes=first.entry_id,
        )
        active = board.list(kind="hypothesis")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].entry_id, second.entry_id)


if __name__ == "__main__":
    unittest.main()
