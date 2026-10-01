"""Deterministic offline scenario generator tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.scenario_generator import (
    ScenarioSpec,
    generate_ohlcv_rows,
    materialize_scenario,
    spec_from_request,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore


class ScenarioGeneratorUnitTests(unittest.TestCase):
    def test_deterministic_same_seed(self) -> None:
        spec = spec_from_request({"preset": "crash_recovery", "seed": 99, "symbol": "BTCUSDT"})
        a = generate_ohlcv_rows(spec)
        b = generate_ohlcv_rows(spec)
        self.assertEqual(len(a), len(b))
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[-1], b[-1])
        self.assertTrue(all(r["low"] <= r["open"] <= r["high"] for r in a))
        self.assertTrue(all(r["low"] <= r["close"] <= r["high"] for r in a))

    def test_materialize_writes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = ScenarioSpec(scenario_id="t1", seed=1)
            spec = spec_from_request({"preset": "range_chop", "seed": 1, "scenarioId": "t1"})
            out = materialize_scenario(markets_root=Path(tmp), spec=spec)
            self.assertTrue(Path(out["path"]).exists())
            self.assertGreater(int(out["barCount"]), 10)


class ScenarioServiceTests(unittest.TestCase):
    def test_create_offline_scenario_registers_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            plane.providers = MagicMock()
            res = plane.create_offline_scenario(
                {"preset": "trend_up", "seed": 7, "symbol": "ETHUSDT", "timeframe": "1h"}
            )
            self.assertTrue(res["truth"]["deterministic_from_spec"])
            self.assertEqual(res["source"]["symbol"], "ETHUSDT")
            self.assertTrue(Path(res["scenario"]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
