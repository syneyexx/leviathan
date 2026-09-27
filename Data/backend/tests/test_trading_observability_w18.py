"""Observability trading category (Wave 18 / gate G49)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


def _csv(path: Path, n: int = 40) -> None:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(hours=i)).isoformat()
            px = 100.0 + i
            fh.write(f"{ts},{px},{px + 1},{px - 1},{px},10\n")


class TradingObservabilityTests(unittest.TestCase):
    def test_lifecycle_events_use_trading_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            _csv(markets / "OBS_1h.csv")
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            plane.scan_market_data()
            events = plane.list_lifecycle_events()
            self.assertTrue(events)
            self.assertTrue(all(e.get("category") == "trading" for e in events))
            self.assertTrue(any(e.get("name") == "market_data.scan" for e in events))
            # Payloads are bounded to keys/refs — no giant dumps.
            for e in events:
                self.assertIn("payload_keys", e)
                self.assertLessEqual(len(e["payload_keys"]), 32)


if __name__ == "__main__":
    unittest.main()
