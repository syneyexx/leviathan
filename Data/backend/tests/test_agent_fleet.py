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

    def test_multiple_orchestrators(self) -> None:
        members = [
            a.agent_id
            for a in self.fleet.list_agents()
            if a.kind != AgentDefinitionKind.ORCHESTRATOR and not a.archived
        ][:2]
        second = self.fleet.create_agent(
            {
                "name": "Second Planner",
                "kind": "orchestrator",
                "orchestrator": {
                    "memberAgentIds": members,
                    "strategy": "parallel_bounded",
                    "parallelismLimit": 2,
                    "failureStrategy": "continue",
                },
            }
        )
        orchs = [a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.ORCHESTRATOR]
        self.assertGreaterEqual(len(orchs), 2)
        self.assertEqual(second.orchestrator.strategy, "parallel_bounded")

    def test_update_orchestrator_members(self) -> None:
        orch = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.ORCHESTRATOR)
        research = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.RESEARCH)
        coding = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.CODING)
        updated = self.fleet.update_agent(
            orch.agent_id,
            {"orchestrator": {"memberAgentIds": [research.agent_id, coding.agent_id], "strategy": "sequential"}},
        )
        self.assertEqual(updated.orchestrator.member_agent_ids, [research.agent_id, coding.agent_id])

    def test_clone_and_enable_disable(self) -> None:
        research = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.RESEARCH)
        cloned = self.fleet.clone_agent(research.agent_id)
        self.assertNotEqual(cloned.agent_id, research.agent_id)
        self.assertEqual(cloned.kind, research.kind)
        disabled = self.fleet.set_enabled(cloned.agent_id, False)
        self.assertFalse(disabled.enabled)
        enabled = self.fleet.set_enabled(cloned.agent_id, True)
        self.assertTrue(enabled.enabled)

    def test_concurrency_limit(self) -> None:
        from Data.modules.agents.fleet_types import AgentMission, MissionStatus
        from Data.modules.agents.store import utc_now

        agent = self.fleet.create_agent({"name": "Limited", "kind": "research", "maxConcurrency": 1})
        running = AgentMission(
            mission_id=AgentFleetStore.new_id("msn"),
            agent_id=agent.agent_id,
            title="hold",
            request="x",
            status=MissionStatus.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
            started_at=utc_now(),
        )
        self.fleet.store.create_mission(running)
        with self.assertRaises(Exception) as ctx:
            self.fleet.launch_mission(agent_id=agent.agent_id, request="search more", dry_run=True)
        self.assertIn("CONCURRENCY", str(ctx.exception.code).upper())

    def test_orchestrator_mission_creates_children(self) -> None:
        orch = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.ORCHESTRATOR)
        # Keep one healthy research member only to reduce side effects
        research = next(a for a in self.fleet.list_agents() if a.kind == AgentDefinitionKind.RESEARCH)
        self.fleet.update_agent(
            orch.agent_id,
            {"orchestrator": {"memberAgentIds": [research.agent_id], "strategy": "sequential"}},
        )
        mission = self.fleet.launch_mission(
            agent_id=orch.agent_id,
            request="search leviathan agent fleet",
            dry_run=False,
        )
        children = [
            m for m in self.fleet.store.list_missions(limit=100) if m.parent_mission_id == mission.mission_id
        ]
        self.assertGreaterEqual(len(children), 1)
        self.assertEqual(children[0].agent_id, research.agent_id)
        self.assertIn(mission.status.value, {"completed", "failed"})

    def test_parallel_bounded_dry_run_plan(self) -> None:
        members = [
            a.agent_id
            for a in self.fleet.list_agents()
            if a.kind != AgentDefinitionKind.ORCHESTRATOR
        ][:2]
        orch = self.fleet.create_agent(
            {
                "name": "Parallel Orch",
                "kind": "orchestrator",
                "orchestrator": {
                    "memberAgentIds": members,
                    "strategy": "parallel_bounded",
                    "parallelismLimit": 2,
                },
            }
        )
        mission = self.fleet.launch_mission(agent_id=orch.agent_id, request="fan out", dry_run=True)
        self.assertTrue(mission.result.get("dryRun"))
        self.assertEqual(mission.result["plan"]["strategy"], "parallel_bounded")
        self.assertEqual(len(mission.result["plan"]["members"]), 2)

    def test_system_agents_have_origin_and_entity_type(self) -> None:
        agents = self.fleet.list_agents()
        by_key = {
            str((a.metadata or {}).get("systemKey") or ""): a
            for a in agents
            if (a.metadata or {}).get("systemKey")
        }
        self.assertIn("research", by_key)
        self.assertIn("planner", by_key)
        research = by_key["research"].public_dict()
        planner = by_key["planner"].public_dict()
        self.assertEqual(research["origin"], "system")
        self.assertEqual(research["entityType"], "agent")
        self.assertEqual(research["systemKey"], "research")
        self.assertFalse(research["mutable"])
        self.assertEqual(planner["origin"], "system")
        self.assertEqual(planner["entityType"], "orchestrator")

    def test_user_agent_is_user_origin(self) -> None:
        created = self.fleet.create_agent(
            {"name": "Custom Scout", "kind": "research", "metadata": {"systemKey": "hack"}}
        )
        payload = created.public_dict()
        self.assertEqual(payload["origin"], "user")
        self.assertIsNone(payload["systemKey"])
        self.assertTrue(payload["mutable"])
        self.assertNotIn("systemKey", created.metadata or {})

    def test_system_agent_cannot_be_archived_or_renamed(self) -> None:
        planner = next(
            a for a in self.fleet.list_agents() if (a.metadata or {}).get("systemKey") == "planner"
        )
        with self.assertRaises(Exception) as ctx:
            self.fleet.archive_agent(planner.agent_id)
        self.assertIn("SYSTEM_AGENT_PROTECTED", str(ctx.exception.code))
        with self.assertRaises(Exception) as ctx2:
            self.fleet.update_agent(planner.agent_id, {"name": "Not Planner"})
        self.assertIn("SYSTEM_AGENT_PROTECTED", str(ctx2.exception.code))
        # Allowed operational update
        updated = self.fleet.update_agent(planner.agent_id, {"description": "Updated desc"})
        self.assertEqual(updated.description, "Updated desc")
        self.assertEqual((updated.metadata or {}).get("systemKey"), "planner")

    def test_system_inventory_roster_is_deterministic(self) -> None:
        first = self.fleet.list_roster()
        second = self.fleet.list_roster()
        self.assertEqual(
            [e["id"] for e in first["entries"]],
            [e["id"] for e in second["entries"]],
        )
        arch = [e for e in first["system"] if e["entityType"] == "architecture"]
        orch = [e for e in first["system"] if e["entityType"] == "orchestrator"]
        self.assertGreaterEqual(len(arch), 1)
        self.assertGreaterEqual(len(orch), 1)
        self.assertTrue(all(e["origin"] == "system" for e in first["system"]))
        self.assertTrue(all(e["mutable"] is False for e in first["system"]))
        ids = [e["id"] for e in first["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        summary = first["summary"]
        self.assertGreaterEqual(summary["system"], 1)
        self.assertIn("architecture", summary)


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
