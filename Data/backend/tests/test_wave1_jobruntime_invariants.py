"""Wave 1 — JobRuntime composition invariants (focused).

Patterns follow test_trading_orchestra.py / test_agent_fleet.py.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.agents import AgentDefinitionKind, AgentFleetService, AgentFleetStore, AgentRuntime
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.market_sim.orchestra import TradingOrchestraService
from Data.modules.market_sim.orchestra.store import OrchestraStore
from Data.modules.workers.pools import POOL_CATALOG


class JobRuntimeCompositionInvariants(unittest.TestCase):
    def test_production_composition_agent_fleet_has_job_runtime_when_externalized(self) -> None:
        """AgentFleet holds JobRuntime when externalized (production composition)."""
        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        self.addCleanup(
            lambda: (
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
                if prev is None
                else os.environ.__setitem__("LEVIATHAN_WORKERS_EXTERNALIZE_API", prev)
            )
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "fleet.db"
        store = JobStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        runtime = JobRuntime(store, gateway, ResourceManager(2))
        fleet = AgentFleetService(
            AgentFleetStore(db),
            AgentRuntime(gateway=gateway, agents_enabled=True),
            job_runtime=runtime,
        )
        fleet.initialize(seed_defaults=True)
        self.assertIsNotNone(fleet.job_runtime)
        self.assertTrue(fleet._runners_externalized())
        self.assertIsInstance(fleet.job_runtime, JobRuntime)

    def test_trading_orchestra_has_fleet_with_job_runtime_when_bound(self) -> None:
        """TradingOrchestra production path binds Fleet that carries JobRuntime."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "orch.db"
        store = JobStore(db)
        store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        runtime = JobRuntime(store, gateway, ResourceManager(2))
        fleet = AgentFleetService(
            AgentFleetStore(db),
            AgentRuntime(gateway=gateway, agents_enabled=True),
            job_runtime=runtime,
        )
        fleet.initialize(seed_defaults=True)
        orchestra = TradingOrchestraService(
            store=OrchestraStore(db),
            fleet=None,
            job_runtime=runtime,
            enabled=True,
        )
        orchestra.bind_fleet(fleet)
        orchestra.bind_job_runtime(runtime)
        self.assertIsNotNone(orchestra.fleet)
        self.assertIsNotNone(orchestra.job_runtime)
        self.assertIs(orchestra.fleet.job_runtime, runtime)
        self.assertIsInstance(orchestra.job_runtime, JobRuntime)
        # Trading kind executor registered on fleet (production bind path).
        self.assertIsNotNone(fleet.kind_executor(AgentDefinitionKind.TRADING))

    def test_worker_fabric_agents_pool_claims_agent_star(self) -> None:
        agents = POOL_CATALOG["agents"]
        self.assertTrue(
            any(str(k).startswith("agent.") for k in agents.job_kinds),
            msg=f"agents pool must claim agent.* jobs, got {agents.job_kinds}",
        )

    def test_unavailable_job_runtime_fails_clearly(self) -> None:
        prev = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        self.addCleanup(
            lambda: (
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
                if prev is None
                else os.environ.__setitem__("LEVIATHAN_WORKERS_EXTERNALIZE_API", prev)
            )
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "fleet.db"
        gateway = ExecutionGateway(catalog=build_default_catalog())
        fleet = AgentFleetService(
            AgentFleetStore(db),
            AgentRuntime(gateway=gateway, agents_enabled=True),
            job_runtime=None,
        )
        fleet.initialize(seed_defaults=True)
        with self.assertRaises(RuntimeError) as ctx:
            fleet.enqueue_advance("missing-mission")
        self.assertIn("job_runtime not bound", str(ctx.exception))

        # Launch path also fails clearly when externalized without JobRuntime.
        from Data.modules.agents.fleet import AgentFleetError

        agent = next(a for a in fleet.list_agents() if a.kind != AgentDefinitionKind.ORCHESTRATOR)
        with self.assertRaises(AgentFleetError) as launch_ctx:
            fleet.launch_mission(agent_id=agent.agent_id, request="noop research")
        self.assertIn("MISSION_WORKER_UNAVAILABLE", str(launch_ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
