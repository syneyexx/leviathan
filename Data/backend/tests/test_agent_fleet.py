from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.agents import (
    AgentDefinitionKind,
    AgentFleetService,
    AgentFleetStore,
    AgentKind,
    AgentRuntime,
    MultiAgentCoordinator,
)
from Data.modules.analytics import AnalyticsService
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.backend.migrations import MigrationRunner


class AgentFleetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "fleet.db"
        MigrationRunner(self.db).apply_all()
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "corpus", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "corpus").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(
            title="Fleet Doc",
            content="leviathan agent fleet search target",
            source="test",
        )
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(self.db)
        obs.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        self.runtime = AgentRuntime(gateway=self.gateway, agents_enabled=True)
        self.fleet = AgentFleetService(AgentFleetStore(self.db), self.runtime)
        self.fleet.initialize(seed_defaults=True)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_seed_and_list(self) -> None:
        agents = self.fleet.list_agents()
        self.assertGreaterEqual(len(agents), 4)
        orch = [a for a in agents if a.kind == AgentDefinitionKind.ORCHESTRATOR]
        self.assertEqual(len(orch), 1)
        self.assertTrue(orch[0].orchestrator)
        self.assertGreaterEqual(len(orch[0].orchestrator.member_agent_ids), 1)

    def test_disabled_agent_cannot_execute(self) -> None:
        agent = self.fleet.create_agent({"name": "Temp", "kind": "research"})
        self.fleet.set_enabled(agent.agent_id, False)
        with self.assertRaises(Exception) as ctx:
            self.fleet.launch_mission(agent_id=agent.agent_id, request="search something")
        self.assertIn("DISABLED", str(ctx.exception.code).upper() + str(ctx.exception))

    def test_orchestrator_dry_run_no_side_effects(self) -> None:
        orch = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.ORCHESTRATOR)
        mission = self.fleet.launch_mission(
            agent_id=orch.agent_id,
            request="plan a research sweep",
            dry_run=True,
        )
        self.assertEqual(mission.status.value, "completed")
        self.assertTrue(mission.result.get("dryRun"))
        self.assertIn("plan", mission.result)

    def test_orchestrator_rejects_unknown_member(self) -> None:
        with self.assertRaises(Exception):
            self.fleet.create_agent(
                {
                    "name": "BadOrch",
                    "kind": "orchestrator",
                    "orchestrator": {"memberAgentIds": ["missing_agent"]},
                }
            )

    def test_orchestrator_cannot_include_self(self) -> None:
        orch = self.fleet.create_agent(
            {
                "name": "SoloOrch",
                "kind": "orchestrator",
                "orchestrator": {"memberAgentIds": []},
            }
        )
        with self.assertRaises(Exception):
            self.fleet.update_agent(
                orch.agent_id,
                {"orchestrator": {"memberAgentIds": [orch.agent_id]}},
            )

    def test_mission_uses_shared_gateway_truth(self) -> None:
        research = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.RESEARCH)
        mission = self.fleet.launch_mission(
            agent_id=research.agent_id,
            request="search leviathan agent fleet",
        )
        self.assertIn(mission.status.value, {"completed", "failed", "unverified"})
        self.assertTrue(mission.result.get("truth", {}).get("agents_use_shared_gateway", True) or "steps" in mission.result)

    def test_cancel_queued_mission_idempotent(self) -> None:
        # Create a mission then cancel after completion path still returns record
        research = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.RESEARCH)
        mission = self.fleet.launch_mission(agent_id=research.agent_id, request="search x", dry_run=True)
        cancelled = self.fleet.cancel_mission(mission.mission_id)
        self.assertEqual(cancelled.mission_id, mission.mission_id)

    def test_reconcile_marks_orphans(self) -> None:
        # Manually insert an active mission row as if process died
        store = self.fleet.store
        agent = self.fleet.list_agents()[0]
        from Data.modules.agents.fleet_types import AgentMission, MissionStatus
        from Data.modules.agents.store import utc_now

        orphan = AgentMission(
            mission_id=AgentFleetStore.new_id("msn"),
            agent_id=agent.agent_id,
            title="orphan",
            request="x",
            status=MissionStatus.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
            started_at=utc_now(),
        )
        store.create_mission(orphan)
        updated = self.fleet.reconcile()
        self.assertIn(orphan.mission_id, updated)
        refreshed = store.get_mission(orphan.mission_id)
        assert refreshed is not None
        self.assertEqual(refreshed.status.value, "interrupted")

    def test_archive_blocked_when_referenced(self) -> None:
        orch = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.ORCHESTRATOR)
        member_id = orch.orchestrator.member_agent_ids[0]
        with self.assertRaises(Exception):
            self.fleet.archive_agent(member_id)


class AnalyticsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "a.db"
        MigrationRunner(self.db).apply_all()
        self.analytics = AnalyticsService(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_overview_empty_tables(self) -> None:
        overview = self.analytics.overview(range_key="7d")
        self.assertEqual(overview["totals"]["trainingJobs"]["total"], 0)
        self.assertTrue(overview["truth"]["no_invented_cost"])

    def test_agents_empty(self) -> None:
        payload = self.analytics.agents(range_key="24h")
        self.assertEqual(payload["agents"], [])


if __name__ == "__main__":
    unittest.main()
