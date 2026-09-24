"""Agent fleet durable advancement via Job Kernel + agents pool."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.agents.fleet import AgentFleetService
from Data.modules.agents.fleet_types import MissionStatus
from Data.modules.agents.runtime import AgentRuntime
from Data.modules.agents.store import AgentFleetStore
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.jobs.states import JobState
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.workers.pools import pool_for_capability


class AgentAdvanceExternalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "agents.db"
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "corpus", chunk_max_chars=200)
        knowledge.initialize()
        (root / "corpus").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(
            title="Agent Doc",
            content="leviathan agent fleet durable advance",
            source="test",
        )
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
        )
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.jobs = JobRuntime(self.job_store, self.gateway, ResourceManager(2))
        self.runtime = AgentRuntime(gateway=self.gateway, jobs=self.jobs, agents_enabled=True)
        self.fleet = AgentFleetService(
            AgentFleetStore(self.db),
            self.runtime,
            job_runtime=self.jobs,
        )
        self.fleet.initialize(seed_defaults=True)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_capability_and_pool_routing(self) -> None:
        self.assertIn("agent.advance", EXTERNAL_WORKER_CAPABILITIES)
        self.assertEqual(pool_for_capability("agent.advance"), "agents")
        ids = {item.id for item in build_default_catalog().list()}
        self.assertIn("agent.advance", ids)

    def test_launch_externalize_enqueues_durable_job(self) -> None:
        research = next(a for a in self.fleet.list_agents() if a.kind.value == "research")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            mission = self.fleet.launch_mission(
                agent_id=research.agent_id,
                request="search leviathan agent fleet durable advance",
            )
        self.assertEqual(mission.status, MissionStatus.QUEUED)
        jobs = self.job_store.list(limit=20)
        advance = [j for j in jobs if j.capability_id == "agent.advance"]
        self.assertEqual(len(advance), 1)
        self.assertEqual(advance[0].arguments.get("mission_id"), mission.mission_id)
        self.assertTrue(
            (advance[0].idempotency_key or "").startswith(f"agent:advance:{mission.mission_id}:")
        )
        again = self.fleet.enqueue_advance(mission.mission_id)
        self.assertEqual(again.job_id, advance[0].job_id)

    def test_launch_legacy_still_executes_inline(self) -> None:
        research = next(a for a in self.fleet.list_agents() if a.kind.value == "research")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "0"}):
            mission = self.fleet.launch_mission(
                agent_id=research.agent_id,
                request="search leviathan agent fleet durable advance",
            )
        self.assertIn(mission.status.value, {"completed", "failed", "disabled"})
        jobs = self.job_store.list(limit=20)
        self.assertFalse(any(j.capability_id == "agent.advance" for j in jobs))

    def test_start_background_externalize_enqueues_queued(self) -> None:
        research = next(a for a in self.fleet.list_agents() if a.kind.value == "research")
        # Force a queued row without going through launch enqueue path.
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "0"}):
            # Create via dry_run then manually reset — simpler: create mission row.
            from Data.modules.agents.fleet_types import AgentMission
            from Data.modules.agents.store import utc_now

            queued = AgentMission(
                mission_id=AgentFleetStore.new_id("msn"),
                agent_id=research.agent_id,
                title="queued",
                request="search leviathan",
                status=MissionStatus.QUEUED,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.fleet.store.create_mission(queued)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            self.fleet.start_background()
        jobs = self.job_store.list(limit=20)
        self.assertTrue(
            any(
                j.capability_id == "agent.advance"
                and (j.arguments or {}).get("mission_id") == queued.mission_id
                for j in jobs
            )
        )

    def test_reconcile_preserves_queued_when_externalized(self) -> None:
        research = next(a for a in self.fleet.list_agents() if a.kind.value == "research")
        from Data.modules.agents.fleet_types import AgentMission
        from Data.modules.agents.store import utc_now

        queued = AgentMission(
            mission_id=AgentFleetStore.new_id("msn"),
            agent_id=research.agent_id,
            title="keep",
            request="x",
            status=MissionStatus.QUEUED,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.fleet.store.create_mission(queued)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            updated = self.fleet.reconcile()
        self.assertNotIn(queued.mission_id, updated)
        refreshed = self.fleet.store.get_mission(queued.mission_id)
        assert refreshed is not None
        self.assertEqual(refreshed.status, MissionStatus.QUEUED)

    def test_worker_handler_advances_mission(self) -> None:
        from Data.modules.workers.entrypoints.agents import _handler

        research = next(a for a in self.fleet.list_agents() if a.kind.value == "research")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            mission = self.fleet.launch_mission(
                agent_id=research.agent_id,
                request="search leviathan agent fleet durable advance",
            )
            job = self.fleet.enqueue_advance(mission.mission_id)
        claimed = self.job_store.transition(job.job_id, JobState.RUNNING)
        ctx = {
            "settings": type(
                "S",
                (),
                {
                    "database_path": self.db,
                    "features": type("F", (), {"agents_enabled": True})(),
                },
            )(),
            "job_store": self.job_store,
            "job_runtime": self.jobs,
            "gateway": self.gateway,
        }
        _handler(ctx, claimed)
        done = self.fleet.store.get_mission(mission.mission_id)
        assert done is not None
        self.assertIn(done.status.value, {"completed", "failed", "disabled", "cancelled"})
        finished_job = self.job_store.get(job.job_id)
        assert finished_job is not None
        self.assertEqual(finished_job.state, JobState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
