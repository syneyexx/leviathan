"""Paper Trading operator surface — bars read path + portfolio flatten (#191)."""

from __future__ import annotations

import os
import tempfile
import threading
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
        # Unit-test the in-process provider path; production externalized mode
        # refuses Control Plane fallback without a bound job_runtime (#191).
        prev_ext = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        prev_runner = os.environ.get("LEVIATHAN_MARKET_SIM_RUNNER")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "0"
        os.environ["LEVIATHAN_MARKET_SIM_RUNNER"] = "inprocess"
        try:
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
        finally:
            if prev_ext is None:
                os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
            else:
                os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = prev_ext
            if prev_runner is None:
                os.environ.pop("LEVIATHAN_MARKET_SIM_RUNNER", None)
            else:
                os.environ["LEVIATHAN_MARKET_SIM_RUNNER"] = prev_runner

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
            self.assertTrue(out["truth"]["paper_only"])
            self.assertTrue(out["truth"]["resume_required"])
            self.assertEqual(out["pause_state"], "PAUSED")
            self.assertTrue(out["kill_switch"])
            pf = plane.get_portfolio(pid)
            self.assertEqual(pf["status"], "PAUSED")
            self.assertTrue(pf["kill_switch"])

    def test_flatten_closes_positions_and_blocks_tick(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            pf = plane.create_portfolio(
                name="Race",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "max_position_pct": 80,
                    "per_trade_risk_pct": 80,
                    "asset_concentration_pct": 80,
                    "max_symbol_exposure_pct": 80,
                },
            )
            pid = pf["portfolio_id"]
            plane.start_portfolio(pid)
            filled = plane.portfolio_place_order(
                pid, symbol="BTCUSDT", side="BUY", qty=1.0, client_order_id="open-1"
            )
            self.assertEqual(filled["order"]["status"], "filled", filled)

            out = plane.portfolio_flatten_all(pid)
            self.assertGreaterEqual(out["flattened"], 1)
            self.assertEqual(out["pause_state"], "PAUSED")
            self.assertTrue(out["kill_switch"])
            self.assertTrue(out["truth"]["paper_only"])
            self.assertEqual(len(out["remaining_positions"]), 0)

            tick = plane.portfolios.autonomous_tick(
                pid,
                decision={
                    "decision_id": "d1",
                    "symbol": "BTCUSDT",
                    "action": "BUY",
                    "requested_qty": 1.0,
                },
            )
            self.assertTrue(tick.get("skipped"))
            self.assertTrue(
                "PAUSED" in str(tick.get("reason") or "")
                or "no_new_exposure" in str(tick.get("reason") or "")
            )

            plane.resume_portfolio(pid)
            pf2 = plane.get_portfolio(pid)
            self.assertEqual(pf2["status"], "RUNNING")
            self.assertFalse(pf2["kill_switch"])

    def test_tick_racing_with_flatten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.return_value = {"price": 50.0, "symbol": "ETHUSDT"}
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            pf = plane.create_portfolio(
                name="Concurrent",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 0,
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "max_position_pct": 80,
                    "per_trade_risk_pct": 80,
                    "asset_concentration_pct": 80,
                    "max_symbol_exposure_pct": 80,
                },
            )
            pid = pf["portfolio_id"]
            plane.start_portfolio(pid)
            plane.portfolio_place_order(
                pid, symbol="ETHUSDT", side="BUY", qty=2.0, client_order_id="race-open"
            )

            outcomes: list[dict] = []

            def _tick() -> None:
                for i in range(5):
                    outcomes.append(
                        plane.portfolios.autonomous_tick(
                            pid,
                            decision={
                                "decision_id": f"tick-{i}",
                                "symbol": "ETHUSDT",
                                "action": "BUY",
                                "requested_qty": 0.5,
                                "client_order_id": f"tick-ord-{i}",
                            },
                        )
                    )

            def _flatten() -> None:
                outcomes.append(plane.portfolio_flatten_all(pid))

            t1 = threading.Thread(target=_tick)
            t2 = threading.Thread(target=_flatten)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            final = plane.get_portfolio(pid)
            self.assertEqual(final["status"], "PAUSED")
            self.assertTrue(final["kill_switch"])
            dash = plane.portfolio_dashboard(pid)
            self.assertEqual(len(dash.get("positions") or []), 0)
            flatten_results = [o for o in outcomes if "flattened" in o]
            self.assertTrue(flatten_results)
            self.assertTrue(flatten_results[0]["truth"]["paper_only"])


if __name__ == "__main__":
    unittest.main()
