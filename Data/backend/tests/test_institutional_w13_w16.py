"""WAVES 13–16 — execution lab, multi-timescale, event intel, portefeuille intelligence."""

from __future__ import annotations

import unittest
from decimal import Decimal

from Data.modules.market_sim.accounting import money
from Data.modules.market_sim.causality import MarketView, SimulationClock
from Data.modules.market_sim.event_intel import (
    EarningsEvent,
    FundamentalObservation,
    build_event_intelligence_bundle,
    filter_fundamentals_as_of,
    filter_news_records_as_of,
)
from Data.modules.market_sim.execution import (
    TemporaryImpactAssumption,
    make_intent,
    schedule_twap_slices,
    schedule_vwap_weights,
)
from Data.modules.market_sim.market_state import MultiTimeframeView, build_multi_horizon_state
from Data.modules.market_sim.portefeuille.intelligence import institutional_exposure_intelligence
from Data.modules.market_sim.portefeuille.ledger import PortfolioBook
from Data.modules.market_sim.types import Bar
from Data.modules.market_sim.universe import CorporateAction


def _bars(n: int = 40) -> list[Bar]:
    out: list[Bar] = []
    px = 100.0
    for i in range(n):
        px = px * 1.001
        day = 1 + i // 24
        hour = i % 24
        ts = f"2024-01-{day:02d}T{hour:02d}:00:00+00:00"
        out.append(Bar(ts, px, px * 1.01, px * 0.99, px * 1.001, 1000 + i))
    return out


class ExecutionLabW13Tests(unittest.TestCase):
    def test_twap_slices_and_assumed_impact(self) -> None:
        intent = make_intent(
            run_id="r1",
            agent_id="a1",
            wallet_id="w1",
            side="BUY",
            qty=Decimal("10"),
            decision_bar_index=0,
            decision_ts="2024-01-01T00:00:00+00:00",
            info_version="iv",
        )
        impact = TemporaryImpactAssumption(bps_per_participation_pct=1.0)
        slices = schedule_twap_slices(intent, n_slices=4, bar_volume=100.0, impact=impact)
        self.assertEqual(len(slices), 4)
        self.assertEqual(sum(s.qty for s in slices), Decimal("10"))
        self.assertTrue(all(s.assumed_impact_bps > 0 for s in slices))
        self.assertFalse(slices[0].public_dict()["truth"]["observed_execution"])
        self.assertEqual(impact.public_dict()["status"], "ASSUMED")

    def test_vwap_weights(self) -> None:
        intent = make_intent(
            run_id="r1",
            agent_id="a1",
            wallet_id="w1",
            side="SELL",
            qty=Decimal("100"),
            decision_bar_index=1,
            decision_ts="2024-01-01T01:00:00+00:00",
            info_version="iv",
        )
        slices = schedule_vwap_weights(intent, volume_weights=[1, 2, 1])
        self.assertEqual(len(slices), 3)
        self.assertEqual(sum(s.qty for s in slices), Decimal("100"))


class MultiTimescaleW14Tests(unittest.TestCase):
    def test_multi_horizon_pack(self) -> None:
        bars = _bars(48)
        clock = SimulationClock(bars=bars)
        clock.index = len(bars) - 1
        base = MarketView(clock=clock, instrument="TEST", timeframe="1h")
        mt = MultiTimeframeView(base=base)
        from Data.modules.market_sim.market_state import synthesize_higher_timeframe

        higher = synthesize_higher_timeframe(base, target_timeframe="4h")
        mt.frames["4h"] = higher
        pack = build_multi_horizon_state(mt, lookback=40)
        self.assertEqual(pack["asOf"], bars[-1].ts)
        self.assertIn("1h", pack["states"])
        self.assertIn("4h", pack["states"])
        self.assertTrue(pack["truth"]["shared_as_of"])
        self.assertIn("alignedFeatures", pack)


class EventIntelW15Tests(unittest.TestCase):
    def test_fundamentals_fail_closed(self) -> None:
        rows = [
            FundamentalObservation("AAPL", "eps", 1.2, "2024-01-01T00:00:00+00:00", "2024-01-05T00:00:00+00:00"),
            FundamentalObservation("AAPL", "eps", 1.5, "2024-02-01T00:00:00+00:00", "2024-02-05T00:00:00+00:00"),
        ]
        kept = filter_fundamentals_as_of(rows, as_of="2024-01-10T00:00:00+00:00")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].value, 1.2)

    def test_event_bundle_and_news(self) -> None:
        bundle = build_event_intelligence_bundle(
            as_of="2024-03-01T00:00:00+00:00",
            symbol="AAPL",
            fundamentals=[
                FundamentalObservation("AAPL", "revenue", 100.0, "2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00"),
            ],
            earnings=[
                EarningsEvent("AAPL", "2023Q4", "2024-01-01T00:00:00+00:00", "2024-01-01T21:00:00+00:00", eps_actual=1.1, eps_estimate=1.0),
            ],
            corporate_actions=[
                CorporateAction("AAPL", "split", "2024-02-01T00:00:00+00:00", factor=2.0),
            ],
        )
        self.assertEqual(bundle["counts"]["fundamentals"], 1)
        self.assertEqual(bundle["counts"]["earnings"], 1)
        self.assertEqual(bundle["counts"]["corporateActions"], 1)
        self.assertTrue(bundle["truth"]["no_auto_price_adjustment"])
        news = filter_news_records_as_of(
            [
                {"available_at": "2024-04-01T00:00:00+00:00", "title": "future"},
                {"available_at": "2024-02-01T00:00:00+00:00", "title": "past"},
                {"title": "missing"},
            ],
            as_of="2024-03-01T00:00:00+00:00",
        )
        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["title"], "past")


class PortefeuilleIntelligenceW16Tests(unittest.TestCase):
    def test_exposure_intelligence(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=money(100_000))
        book.apply_fill(
            symbol="AAPL",
            side="BUY",
            qty=money(100),
            price=money(150),
            fee=money(1),
            tx_id="t1",
            timestamp="2024-01-01T00:00:00+00:00",
            strategy_id="s1",
        )
        marks = {"AAPL": 160}
        out = institutional_exposure_intelligence(
            book=book,
            marks=marks,
            settings={"asset_concentration_pct": 40.0, "cash_reserve_pct": 10.0, "max_drawdown_pct": 20.0},
            allocations={"AAPL": 20.0},
        )
        self.assertIn("AAPL", out["bySymbol"])
        self.assertEqual(out["allocationDrifts"][0]["status"], "MEASURED")
        self.assertIn("concentration", out["constraints"])
        self.assertTrue(out["truth"]["from_real_portfolio_book"])
        self.assertTrue(out["truth"]["no_factor_risk_engine"])


if __name__ == "__main__":
    unittest.main()
