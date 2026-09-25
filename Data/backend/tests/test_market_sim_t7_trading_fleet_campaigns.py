"""T7 — Trading role executors on Agent Fleet (G24) + durable ResearchCampaign (G25)."""

from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.agents import AgentKind, AgentRuntime
from Data.modules.agents.fleet import AgentFleetService
from Data.modules.agents.fleet_types import (
    AgentDefinitionKind,
    AgentMission,
    MissionStatus,
)
from Data.modules.agents.planner import StructuredAgentPlanner
from Data.modules.agents.store import AgentFleetStore, utc_now as fleet_utc_now
from Data.modules.agents.types import AgentStepKind
from Data.backend.migrations import MigrationRunner
from Data.modules.execution.builtins import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.execution.types import CapabilityRequest, CapabilityStatus
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.gateway_executor import MarketSimModuleExecutor
from Data.modules.market_sim.orchestra.service import TradingMissionExecutor, TradingOrchestraService
from Data.modules.market_sim.research_campaign import ResearchCampaignController, new_campaign
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.types import MarketSimError


class TradingExecutorKindTests(unittest.TestCase):
    """G24 / D17 — TRADING kind, planner refusal, runtime refusal, reconcile skip."""

    def test_agent_kind_trading_exists(self) -> None:
        self.assertIn("TRADING", [m.name for m in AgentKind])
        self.assertEqual(AgentDefinitionKind.TRADING.value, "trading")

    def test_execution_kind_maps_trading(self) -> None:
        src = inspect.getsource(AgentFleetService._execution_kind)
        self.assertIn("AgentKind.TRADING", src)
        self.assertIn("AgentDefinitionKind.TRADING", src)

    def test_planner_refuses_generic_capability_chain(self) -> None:
        plan = StructuredAgentPlanner().plan("analyze BTC", kind=AgentKind.TRADING)
        kinds = [s.kind for s in plan.steps]
        self.assertIn(AgentStepKind.PLAN, kinds)
        self.assertNotIn(AgentStepKind.CAPABILITY, kinds)
        notes = " ".join(s.note or "" for s in plan.steps)
        self.assertIn("TradingMissionExecutor", notes)

    def test_runtime_refuses_generic_execute(self) -> None:
        runtime = AgentRuntime(gateway=None, agents_enabled=True)
        result = runtime.execute("deliberate", kind=AgentKind.TRADING)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("TRADING_EXECUTOR_REQUIRED", result.error or "")

    def test_reconcile_skips_trading_missions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fleet.db"
            MigrationRunner(db).apply_all()
            runtime = AgentRuntime(gateway=None, agents_enabled=True)
            fleet = AgentFleetService(AgentFleetStore(db), runtime)
            fleet.initialize(seed_defaults=False)
            agent = fleet.create_agent(
                {
                    "name": "T7 Trader",
                    "kind": "trading",
                    "role": "market_analyst",
                    "tags": ["trading"],
                }
            )
            orphan = AgentMission(
                mission_id=AgentFleetStore.new_id("msn"),
                agent_id=agent.agent_id,
                title="durable trading",
                request="trading:deliberation",
                status=MissionStatus.RUNNING,
                created_at=fleet_utc_now(),
                updated_at=fleet_utc_now(),
                started_at=fleet_utc_now(),
            )
            fleet.store.create_mission(orphan)
            with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "0"}):
                updated = fleet.reconcile()
            self.assertNotIn(orphan.mission_id, updated)
            refreshed = fleet.store.get_mission(orphan.mission_id)
            assert refreshed is not None
            self.assertEqual(refreshed.status, MissionStatus.RUNNING)

    def test_trading_mission_executor_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            MigrationRunner(db).apply_all()
            runtime = AgentRuntime(gateway=None, agents_enabled=True)
            fleet = AgentFleetService(AgentFleetStore(db), runtime)
            fleet.initialize(seed_defaults=False)
            from Data.modules.market_sim.orchestra.store import OrchestraStore

            orch = TradingOrchestraService(
                store=OrchestraStore(db),
                fleet=None,
                enabled=True,
            )
            orch.bind_fleet(fleet)
            self.assertIsInstance(orch.executor, TradingMissionExecutor)
            self.assertIs(
                fleet._kind_executors.get(AgentDefinitionKind.TRADING),
                orch.executor,
            )


class ResearchCampaignTests(unittest.TestCase):
    """G25 — durable campaign create/start/pause/resume/advance with checkpoint."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        markets = root / "markets"
        markets.mkdir()
        db = root / "db.sqlite"
        self.store = MarketSimStore(db)
        self.store.initialize()
        data = MarketDataStore(self.store, markets)
        self.svc = MarketSimControlPlane(self.store, data, enabled=True)
        created = self.svc.create_strategy(name="t7-camp", parameters={"fast_ma": 5, "slow_ma": 20})
        self.strategy_id = created["strategy"]["strategy_id"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_start_pause_resume_advance(self) -> None:
        camp = self.svc.create_research_campaign(
            strategy_id=self.strategy_id,
            hypothesis="ma cross works in uptrend",
            proposer_agent_id="agent-orch",
            n_bars=100,
            config={"window": 20, "step": 10, "auto_complete_on_windows": False},
        )
        self.assertEqual(camp["status"], "proposed")
        self.assertEqual(camp["phase"], "design")
        self.assertTrue(camp["truth"]["durable"])
        self.assertGreater(camp["checkpoint"]["windows_total"], 0)
        self.assertEqual(camp["checkpoint"]["windows_done"], 0)

        started = self.svc.start_research_campaign(camp["campaign_id"])
        self.assertEqual(started["status"], "running")
        self.assertIsNotNone(started["started_at"])

        advanced = self.svc.advance_research_campaign(camp["campaign_id"], trial_id="trial-1")
        self.assertEqual(advanced["checkpoint"]["windows_done"], 1)
        self.assertEqual(advanced["checkpoint"]["last_window_index"], 0)
        self.assertIn("trial-1", advanced["trial_ids"])

        paused = self.svc.pause_research_campaign(camp["campaign_id"])
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["checkpoint"]["windows_done"], 1)

        # Re-load proves durability across "restart" (new controller, same store).
        reloaded = ResearchCampaignController(self.store).get(camp["campaign_id"])
        self.assertEqual(reloaded["status"], "paused")
        self.assertEqual(reloaded["checkpoint"]["windows_done"], 1)

        resumed = self.svc.resume_research_campaign(camp["campaign_id"])
        self.assertEqual(resumed["status"], "running")
        self.assertIsNotNone(resumed["resumed_at"])
        self.assertEqual(resumed["checkpoint"]["windows_done"], 1)

        again = self.svc.advance_research_campaign(camp["campaign_id"])
        self.assertEqual(again["checkpoint"]["windows_done"], 2)

    def test_advance_requires_running(self) -> None:
        camp = self.svc.create_research_campaign(
            strategy_id=self.strategy_id,
            hypothesis="x",
            n_bars=40,
        )
        with self.assertRaises(MarketSimError) as ctx:
            self.svc.advance_research_campaign(camp["campaign_id"])
        self.assertEqual(ctx.exception.code, "CAMPAIGN_NOT_RUNNING")

    def test_auto_complete_on_windows(self) -> None:
        camp = self.svc.create_research_campaign(
            strategy_id=self.strategy_id,
            hypothesis="finish",
            n_bars=30,
            config={"window": 20, "step": 20, "auto_complete_on_windows": True},
        )
        total = camp["checkpoint"]["windows_total"]
        self.assertGreaterEqual(total, 1)
        self.svc.start_research_campaign(camp["campaign_id"])
        last = camp
        for _ in range(total):
            last = self.svc.advance_research_campaign(camp["campaign_id"])
        self.assertEqual(last["status"], "completed")
        self.assertEqual(last["phase"], "done")
        self.assertIsNotNone(last["finished_at"])

    def test_phase_advance_without_windows(self) -> None:
        camp = new_campaign(
            strategy_id=self.strategy_id,
            hypothesis="phased",
            created_at=utc_now(),
        )
        saved = ResearchCampaignController(self.store).create(camp)
        self.assertEqual(saved["checkpoint"]["windows_total"], 0)
        self.svc.start_research_campaign(saved["campaign_id"])
        phases = []
        cur = saved
        for _ in range(5):
            cur = self.svc.advance_research_campaign(saved["campaign_id"])
            phases.append(cur["phase"])
            if cur["status"] == "completed":
                break
        self.assertEqual(cur["status"], "completed")
        self.assertEqual(cur["phase"], "done")
        self.assertIn("validation", phases)

    def test_cancel_terminal(self) -> None:
        camp = self.svc.create_research_campaign(
            strategy_id=self.strategy_id,
            hypothesis="cancel me",
        )
        cancelled = self.svc.cancel_research_campaign(camp["campaign_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(MarketSimError):
            self.svc.cancel_research_campaign(camp["campaign_id"])


class CampaignGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        markets = root / "markets"
        markets.mkdir()
        db = root / "db.sqlite"
        store = MarketSimStore(db)
        store.initialize()
        data = MarketDataStore(store, markets)
        self.svc = MarketSimControlPlane(store, data, enabled=True)
        catalog = build_default_catalog()
        self.gateway = ExecutionGateway(
            catalog=catalog,
            module_executor=MarketSimModuleExecutor(self.svc),
        )
        created = self.svc.create_strategy(name="gw-camp", parameters={"fast_ma": 3, "slow_ma": 9})
        self.strategy_id = created["strategy"]["strategy_id"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_catalog_registers_campaign_caps(self) -> None:
        catalog = build_default_catalog()
        for cap in (
            "market_sim.campaign.create",
            "market_sim.campaign.start",
            "market_sim.campaign.pause",
            "market_sim.campaign.resume",
            "market_sim.campaign.advance",
            "market_sim.campaign.cancel",
        ):
            self.assertIsNotNone(catalog.get(cap), cap)

    def test_campaign_lifecycle_via_gateway(self) -> None:
        created = self.gateway.execute(
            CapabilityRequest(
                capability_id="market_sim.campaign.create",
                arguments={
                    "strategy_id": self.strategy_id,
                    "hypothesis": "via gateway",
                    "n_bars": 50,
                    "config": {"window": 20, "step": 15, "auto_complete_on_windows": False},
                },
                requested_by="api.market_sim",
                idempotency_key="t7-campaign-create-1",
            )
        )
        self.assertEqual(created.status, CapabilityStatus.COMPLETED)
        out = created.output
        assert isinstance(out, dict)
        inner = out.get("output") or out
        camp = inner["campaign"]
        cid = camp["campaign_id"]

        started = self.gateway.execute(
            CapabilityRequest(
                capability_id="market_sim.campaign.start",
                arguments={"campaign_id": cid},
                requested_by="api.market_sim",
                idempotency_key=f"t7-campaign-start:{cid}",
            )
        )
        self.assertEqual(started.status, CapabilityStatus.COMPLETED)
        advanced = self.gateway.execute(
            CapabilityRequest(
                capability_id="market_sim.campaign.advance",
                arguments={"campaign_id": cid, "trial_id": "t-gw"},
                requested_by="api.market_sim",
            )
        )
        self.assertEqual(advanced.status, CapabilityStatus.COMPLETED)
        adv_out = advanced.output
        assert isinstance(adv_out, dict)
        adv_inner = adv_out.get("output") or adv_out
        self.assertEqual(adv_inner["campaign"]["checkpoint"]["windows_done"], 1)


class Migration47Tests(unittest.TestCase):
    def test_migration_47_present(self) -> None:
        from Data.backend.migrations import MIGRATIONS

        head = MIGRATIONS[-1].version
        self.assertGreaterEqual(head, 47)
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[47], "trading_research_campaigns")


if __name__ == "__main__":
    unittest.main()
