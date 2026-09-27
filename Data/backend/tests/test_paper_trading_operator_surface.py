"""Paper Trading operator surface — bars read path + portfolio flatten."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.providers import ProviderRegistry, ProviderStatus
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import Bar


class _StubProvider:
    provider_id = "stub_public"
    license_note = "test"
    license_state = "TEST"

    def ping(self) -> bool:
        return True

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            reachable=True,
            authenticated=False,
            latency_ms=1.0,
            detail="stub",
            license_note=self.license_note,
            license_state=self.license_state,
        )

    def fetch_historical(self, symbol: str, timeframe: str, *, limit: int = 500, **_kw):
        n = min(limit, 30)
        return [
            Bar(
                ts=f"2026-01-01T{i:02d}:00:00+00:00",
                open=100 + i,
                high=101 + i,
                low=99 + i,
                close=100.5 + i,
                volume=10 + i,
            )
            for i in range(n)
        ]

    def fetch_quote(self, symbol: str):
        return {"price": 130.0, "provider": self.provider_id, "symbol": symbol}


def _plane(tmp: Path) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir(exist_ok=True)
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    return MarketSimControlPlane(store=store, data=data, enabled=True)


class PaperTradingOperatorSurfaceTests(unittest.TestCase):
    def test_fetch_market_bars_returns_provider_bars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            reg = ProviderRegistry()
            reg.register(_StubProvider())  # type: ignore[arg-type]
            plane.providers = reg

            out = plane.fetch_market_bars(
                provider_id="stub_public", symbol="BTCUSDT", timeframe="1h", limit=20
            )
            self.assertEqual(out["count"], 20)
            self.assertEqual(out["bars"][0]["open"], 100)
            self.assertTrue(out["truth"]["not_fabricated"])
            self.assertEqual(out["quote"]["price"], 130.0)

    def test_portfolio_flatten_all_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            row = plane.create_portfolio(name="Flatten Test", initial_equity=50_000)
            pid = row["portfolio_id"]
            out = plane.portfolio_flatten_all(pid)
            self.assertEqual(out["flattened"], 0)
            self.assertTrue(out["truth"]["no_open_positions"])


if __name__ == "__main__":
    unittest.main()
