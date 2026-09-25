"""Tests for Agents dashboard read-model and fleet start/pause-all."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from Data.modules.agents.dashboard import build_agents_dashboard, team_bucket_for_agent
from Data.modules.agents.fleet import AgentFleetService
from Data.modules.agents.fleet_types import (
    AgentDefinition,
    AgentDefinitionKind,
    AgentHealth,
    AgentMission,
    MissionStatus,
)
from Data.modules.agents.runtime import AgentRuntime
from Data.modules.agents.store import AgentFleetStore
from Data.modules.agents.system_inventory import SystemInventory
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.workers.pools import POOL_CATALOG
from Data.modules.workers.registry import WorkerRegistry


def _agent(**kwargs) -> AgentDefinition:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = dict(
        agent_id="agent_x",
        name="X",
        kind=AgentDefinitionKind.RESEARCH,
        description="",
        role="Research",
        enabled=True,
        archived=False,
        capabilities=[],
        tags=["research"],
        memory_policy="default",
        health=AgentHealth.IDLE,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    base.update(kwargs)
    return AgentDefinition(**base)


def _mission(**kwargs) -> AgentMission:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = dict(
        mission_id="m1",
        agent_id="agent_x",
        title="t",
        request="r",
        status=MissionStatus.QUEUED,
        priority="med",
        progress=0.0,
        job_ids=[],
        created_at=now,
        updated_at=now,
    )
    base.update(kwargs)
    return AgentMission(**base)


class DashboardReadModelTests(unittest.TestCase):
    def test_zero_agents_zero_missions(self) -> None:
        payload = build_agents_dashboard(
            agents=[],
            missions=[],
            architecture_entries=[],
            agents_enabled=True,
            workers_payload=None,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(payload["fleet"]["totalAgents"], 0)
        self.assertIsNone(payload["performance"]["successRate"])
        self.assertIsNone(payload["performance"]["avgDurationMs"])
        self.assertEqual(payload["missions"]["active"], 0)
        self.assertFalse(payload["workers"]["available"])
        self.assertIsNone(payload["workers"]["active"])

    def test_success_rate_excludes_cancelled(self) -> None:
        now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        finished = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        started = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        missions = [
            _mission(
                mission_id="c1",
                status=MissionStatus.COMPLETED,
                started_at=started,
                finished_at=finished,
                updated_at=finished,
            ),
            _mission(
                mission_id="f1",
                status=MissionStatus.FAILED,
                started_at=started,
                finished_at=finished,
                updated_at=finished,
            ),
            _mission(
                mission_id="x1",
                status=MissionStatus.CANCELLED,
                started_at=started,
                finished_at=finished,
                updated_at=finished,
            ),
        ]
        payload = build_agents_dashboard(
            agents=[_agent()],
            missions=missions,
            architecture_entries=[],
            agents_enabled=True,
            now=now,
        )
        self.assertEqual(payload["performance"]["eligibleTerminal"], 2)
        self.assertAlmostEqual(payload["performance"]["successRate"], 0.5)
        self.assertEqual(payload["missions"]["cancelledInWindow"], 1)
        self.assertIsNotNone(payload["performance"]["avgDurationMs"])

    def test_architecture_not_counted_as_agents(self) -> None:
        payload = build_agents_dashboard(
            agents=[_agent(agent_id="a1"), _agent(agent_id="a2", name="Y", kind=AgentDefinitionKind.ORCHESTRATOR)],
            missions=[],
            architecture_entries=[
                {"id": "system:architecture:execution_gateway", "entityType": "architecture"},
                {"id": "system:orchestrator:cognitive_runtime", "entityType": "orchestrator"},
            ],
            agents_enabled=True,
        )
        self.assertEqual(payload["fleet"]["totalAgents"], 2)
        self.assertEqual(payload["fleet"]["orchestrators"], 2)  # 1 fleet + 1 system
        self.assertEqual(payload["fleet"]["architecture"], 2)

    def test_memory_linked_excludes_none_policy(self) -> None:
        agents = [
            _agent(agent_id="a1", memory_policy="default"),
            _agent(agent_id="a2", name="B", memory_policy="none"),
            _agent(agent_id="a3", name="C", memory_policy="persistent"),
        ]
        payload = build_agents_dashboard(
            agents=agents,
            missions=[],
            architecture_entries=[],
            agents_enabled=True,
        )
        self.assertEqual(payload["fleet"]["memoryLinked"], 2)

    def test_worker_active_from_registry_states(self) -> None:
        payload = build_agents_dashboard(
            agents=[],
            missions=[],
            architecture_entries=[],
            agents_enabled=True,
            workers_payload={
                "workers": [
                    {"state": "READY"},
                    {"state": "BUSY"},
                    {"state": "STALE"},
                    {"state": "STOPPED"},
                ],
                "pools": [
                    {
                        "pool_id": "agents",
                        "desired": 2,
                        "max_count": 8,
                        "instances": 2,
                        "ready": 1,
                        "busy": 1,
                        "resource_classes": ["CPU_LIGHT"],
                    }
                ],
                "supervisor": {"health": "HEALTHY"},
            },
            jobs_by_pool={"agents": {"queued": 3}},
        )
        self.assertTrue(payload["workers"]["available"])
        self.assertEqual(payload["workers"]["active"], 2)
        self.assertEqual(payload["workers"]["pools"][0]["queue"], 3)

    def test_team_bucket_mapping(self) -> None:
        self.assertEqual(team_bucket_for_agent(_agent(kind=AgentDefinitionKind.CODING)), "Development")
        self.assertEqual(team_bucket_for_agent(_agent(kind=AgentDefinitionKind.TRADING, tags=["trading"])), "Trading")
        self.assertEqual(
            team_bucket_for_agent(_agent(kind=AgentDefinitionKind.SPECIALIST, tags=["review"], name="Critic")),
            "Risk",
        )

    def test_flow_counts_from_mission_status(self) -> None:
        missions = [
            _mission(mission_id="q", status=MissionStatus.QUEUED),
            _mission(mission_id="s", status=MissionStatus.STARTING),
            _mission(mission_id="r", status=MissionStatus.RUNNING),
        ]
        payload = build_agents_dashboard(
            agents=[_agent(kind=AgentDefinitionKind.ORCHESTRATOR)],
            missions=missions,
            architecture_entries=[{"entityType": "orchestrator"}],
            agents_enabled=True,
        )
        self.assertEqual(payload["flow"]["incoming"], 1)
        self.assertEqual(payload["flow"]["routing"], 1)
        self.assertEqual(payload["flow"]["executing"], 1)
        self.assertEqual(payload["flow"]["orchestrators"], 2)
        self.assertIsNone(payload["flow"]["verifying"])
        self.assertIsNone(payload["flow"]["memoryWriteback"])


class FleetStartPauseTests(unittest.TestCase):
    def test_start_pause_all_skips_system(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            store = AgentFleetStore(db)
            gateway = ExecutionGateway()
            runtime = AgentRuntime(gateway=gateway, agents_enabled=True)
            fleet = AgentFleetService(store, runtime, system_inventory=SystemInventory())
            fleet.initialize(seed_defaults=True)
            user = fleet.create_agent(
                {
                    "name": "User Agent",
                    "kind": "research",
                    "role": "User",
                    "enabled": True,
                }
            )
            paused = fleet.disable_all_user_agents()
            self.assertIn(user.agent_id, paused["changed"])
            # System agents remain enabled
            system_agents = [a for a in fleet.list_agents() if (a.metadata or {}).get("systemKey")]
            self.assertTrue(system_agents)
            self.assertTrue(all(a.enabled for a in system_agents))
            reenabled = fleet.enable_all_user_agents()
            self.assertIn(user.agent_id, reenabled["changed"])
            self.assertTrue(fleet.get_agent(user.agent_id).enabled)


class WorkerPoolScaleTests(unittest.TestCase):
    def test_scale_persists_and_enforces_max(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "w.db"
            registry = WorkerRegistry(db)
            registry.initialize()
            pool_id = "agents"
            max_count = POOL_CATALOG[pool_id].max_count
            result = registry.set_pool_desired_count(pool_id, min(2, max_count))
            self.assertEqual(result["desiredCount"], min(2, max_count))
            overrides = registry.list_pool_desired_overrides()
            self.assertEqual(overrides[pool_id], min(2, max_count))
            # Unknown pool still persists at registry layer; API enforces catalog.
            registry.set_pool_desired_count("not_a_real_pool", 1)
            self.assertIn("not_a_real_pool", registry.list_pool_desired_overrides())


if __name__ == "__main__":
    unittest.main()
