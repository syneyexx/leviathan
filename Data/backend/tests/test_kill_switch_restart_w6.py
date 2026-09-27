"""Kill-switch restart persistence (Wave 6 / Wave 14)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


class KillSwitchRestartTests(unittest.TestCase):
    def test_paper_kill_switch_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            db = root / "lev.db"
            store = MarketSimStore(db)
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            session = plane.start_paper_session(
                symbol="BTCUSDT",
                broker_id="local_paper",
                provider_id="csv_local",
                initial_cash=10_000.0,
            )
            sid = session["session_id"]
            plane.paper_kill_switch(sid, armed=True)
            self.assertTrue(plane.paper_session_state(sid)["kill_switch"])

            # Process restart: new control plane, same MARKET DB.
            store2 = MarketSimStore(db)
            data2 = MarketDataStore(store2, markets)
            plane2 = MarketSimControlPlane(store=store2, data=data2, enabled=True)
            restored = plane2.paper_session_state(sid)
            self.assertTrue(restored["kill_switch"])
            with self.assertRaises(MarketSimError) as ctx:
                plane2.paper_place_order(
                    sid,
                    side="BUY",
                    qty=1,
                )
            self.assertEqual(ctx.exception.code, "KILL_SWITCH")


if __name__ == "__main__":
    unittest.main()
