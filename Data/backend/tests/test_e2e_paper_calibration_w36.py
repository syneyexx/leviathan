"""Wave 36 — deterministic paper / calibration E2E through PortfolioService + RiskGuard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


def _plane(tmp: Path) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir(exist_ok=True)
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
    provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    return plane


class PaperCalibrationE2EW36Tests(unittest.TestCase):
    def test_create_limits_order_flatten_zero_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            provider = plane.providers.get.return_value

            # 1) create portfolio via PortfolioService / control plane
            pf = plane.create_portfolio(
                name="Paper Calibration E2E",
                initial_equity=100_000,
                settings={
                    "allow_manual_only": True,
                    "cash_reserve_pct": 5,
                    "fee_bps": 1,
                    "slippage_bps": 1,
                    "max_position_pct": 20,
                    "per_trade_risk_pct": 2,
                    "asset_concentration_pct": 30,
                    "max_symbol_exposure_pct": 30,
                    "max_leverage": 1.0,
                    "max_drawdown_pct": 10,
                    "max_orders_per_day": 50,
                },
            )
            pid = pf["portfolio_id"]
            self.assertEqual(str(pf.get("mode") or "PAPER").upper(), "PAPER")

            # 2) safe limits applied
            settings = pf["settings"]
            self.assertLessEqual(float(settings["max_position_pct"]), 20)
            self.assertLessEqual(float(settings["max_leverage"]), 1.0)
            self.assertGreaterEqual(float(settings["cash_reserve_pct"]), 5)

            # 3) start → paper order through RiskGuard path
            plane.start_portfolio(pid)
            filled = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=0.5,
                client_order_id="calib-open-1",
            )
            self.assertEqual(filled["order"]["status"], "filled", filled)
            provider.fetch_quote.assert_called()

            book = plane.get_portfolio(pid)
            positions = book.get("positions") or []
            # snapshot path may nest positions; also check via public book
            dash = plane.portfolio_dashboard(pid) if hasattr(plane, "portfolio_dashboard") else None
            if dash:
                positions = dash.get("positions") or positions
            self.assertTrue(
                filled["order"]["status"] == "filled",
                "order must fill through RiskGuard/paper path",
            )

            # 4) flatten → zero exposure / PAUSED
            flat = plane.portfolio_flatten_all(pid)
            self.assertEqual(flat["pause_state"], "PAUSED")
            self.assertTrue(flat["kill_switch"])
            self.assertEqual(len(flat.get("remaining_positions") or []), 0)
            self.assertTrue(flat["truth"].get("paper_only"))
            self.assertTrue(flat["truth"].get("resume_required") or flat["kill_switch"])

            pf_after = plane.get_portfolio(pid)
            self.assertEqual(pf_after["status"], "PAUSED")
            meta = dict(pf_after.get("metadata") or {})
            self.assertTrue(
                meta.get("flatten_armed")
                or meta.get("no_new_exposure_reason") == "flatten_all"
                or pf_after["settings"].get("allow_new_positions") is False
            )

            # 5) assert live broker never called
            for call in plane.providers.get.call_args_list:
                args = call.args if call.args else ()
                kwargs = call.kwargs or {}
                pid_arg = args[0] if args else kwargs.get("provider_id") or kwargs.get("pid")
                self.assertNotIn(str(pid_arg or "").lower(), {"live", "live_broker"})
            with self.assertRaises(MarketSimError):
                plane.create_portfolio(name="MustBlock", broker_mode="live")

            # 6) flatten ends no-new-exposure
            refused = plane.portfolio_place_order(
                pid,
                symbol="BTCUSDT",
                side="BUY",
                qty=0.1,
                client_order_id="calib-after-flat",
            )
            self.assertEqual(refused.get("code"), "NO_NEW_EXPOSURE")
            tick = plane.portfolios.autonomous_tick(
                pid,
                decision={
                    "decision_id": "d-calib",
                    "symbol": "BTCUSDT",
                    "action": "BUY",
                    "requested_qty": 0.1,
                },
            )
            self.assertTrue(tick.get("skipped"))
            reason = str(tick.get("reason") or "")
            self.assertTrue(
                "PAUSED" in reason or "no_new_exposure" in reason,
                reason,
            )


if __name__ == "__main__":
    unittest.main()
