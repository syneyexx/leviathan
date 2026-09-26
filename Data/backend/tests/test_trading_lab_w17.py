"""W17 — Trading Center lab API surface (typed real endpoints)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.migrations import MigrationRunner
from Data.backend.routes.market_sim import build_market_sim_router
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.trading_live_guard import LiveTradingGuard


class LabApiTests(unittest.TestCase):
    def test_lab_overview_and_cost_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lab.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(str(db))
            service = SimpleNamespace(
                store=store,
                live_guard=LiveTradingGuard(),
            )
            app = FastAPI()
            app.include_router(build_market_sim_router(service))  # type: ignore[arg-type]
            client = TestClient(app)
            ov = client.get("/api/market-sim/lab/overview")
            self.assertEqual(ov.status_code, 200, ov.text)
            body = ov.json()
            self.assertTrue(body["truth"]["no_mock_kpis"])
            self.assertIn("NO_STRATEGY_QUALIFIED", body["valid_lab_outcomes"])
            self.assertEqual(body["hpo_bayesian_tpe"]["status"], "FEATURE_GATED")
            cost = client.get("/api/market-sim/lab/cost-pack", params={"feeBps": 5, "slippageBps": 2})
            self.assertEqual(cost.status_code, 200)
            self.assertEqual(cost.json()["cost_pack"]["fee"]["status"], "ASSUMED")
            feed = client.post(
                "/api/market-sim/lab/feed-health",
                json={
                    "feedId": "f1",
                    "lastTickTs": "2020-01-01T00:00:00+00:00",
                    "asOf": "2020-01-01T00:01:00+00:00",
                },
            )
            self.assertEqual(feed.status_code, 200)
            self.assertIn(feed.json()["feed_health"]["status"], {"HEALTHY", "STALE", "GAP", "UNMEASURED"})
            trials = client.get("/api/market-sim/lab/trials")
            self.assertEqual(trials.status_code, 200)
            self.assertIn("trials", trials.json())


if __name__ == "__main__":
    unittest.main()
