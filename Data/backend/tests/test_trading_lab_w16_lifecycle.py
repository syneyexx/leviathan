"""W16 — durable agent lab create/start wired to real campaign simulations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.tests.test_market_sim_characterization import FIXTURE
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


class AgentLabLifecycleTests(unittest.TestCase):
    def test_lab_create_start_runs_real_campaign_and_retains_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            (markets / "BTCUSDT_1h.csv").write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            sources = plane.scan_market_data()
            strat = plane.create_strategy(name="lab-strat")
            created = plane.create_agent_lab(
                name="fixture lab",
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                max_candidates=2,
                max_iterations=2,
                acceptance_criteria={
                    "min_trades": 1,
                    "max_drawdown_pct": 100.0,
                    "require_val_pass": False,
                    "require_robustness_pass": False,
                },
                autonomy_ceiling="A1",
                enable_learning=False,  # campaign-path characterization
            )
            self.assertEqual(created["status"], "CREATED")
            self.assertTrue(created["campaign_id"])
            self.assertEqual(created["max_candidates"], 2)

            result = plane.start_agent_lab(created["lab_id"])
            lab = result["lab"] if "lab" in result else result
            self.assertIn(lab["status"], {"COMPLETED", "FAILED"})
            self.assertIn(lab["outcome"], {"QUALIFIED_STRATEGY_FOUND", "NO_STRATEGY_QUALIFIED"})
            campaign = lab.get("campaign") or {}
            iterations = (campaign.get("results") or {}).get("iterations") or []
            self.assertTrue(any(it.get("simulation_executed") for it in iterations))
            # Durable reload
            reloaded = plane.get_agent_lab(created["lab_id"])
            self.assertEqual(reloaded["lab_id"], created["lab_id"])
            self.assertEqual(reloaded["outcome"], lab["outcome"])

    def test_lab_cancel_is_honest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            (markets / "BTCUSDT_1h.csv").write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            sources = plane.scan_market_data()
            strat = plane.create_strategy(name="lab-cancel")
            created = plane.create_agent_lab(
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                max_iterations=1,
                enable_learning=False,
            )
            cancelled = plane.cancel_agent_lab(created["lab_id"])
            self.assertEqual(cancelled["status"], "CANCELLED")
            self.assertEqual(cancelled["outcome"], "NO_STRATEGY_QUALIFIED")


if __name__ == "__main__":
    unittest.main()
