"""WAVE 08 — equities and ETF institutional hardening."""

from __future__ import annotations

import unittest
from decimal import Decimal

from Data.modules.market_sim.instruments import (
    EQUITY_AAPL,
    EQUITY_SPY,
    BorrowConstraints,
    InstrumentFamily,
    InstrumentSpec,
    equity_session_is_open,
    infer_family,
    registry_lookup,
    spec_for_symbol,
    support_matrix,
    validate_intent_rules,
)
from Data.modules.market_sim.short_margin import ShortMarginPolicy
from Data.modules.market_sim.universe import PointInTimeUniverse, SessionCalendarDay


class EquitiesEtfW08Tests(unittest.TestCase):
    def test_spy_is_equity_etf_not_separate_family(self) -> None:
        self.assertEqual(EQUITY_SPY.family, InstrumentFamily.EQUITY)
        self.assertTrue(EQUITY_SPY.is_etf)
        self.assertFalse(EQUITY_AAPL.is_etf)
        self.assertIs(registry_lookup("SPY"), EQUITY_SPY)
        pub = EQUITY_SPY.public_dict()
        self.assertTrue(pub["is_etf"])
        self.assertTrue(pub["truth"]["etf_is_equity_family_not_separate_enum"])
        families = {row["family"] for row in support_matrix()["families"]}
        self.assertNotIn("etf", families)

    def test_instrument_type_etf_inference(self) -> None:
        self.assertEqual(
            infer_family("QQQ", metadata={"instrument_type": "etf"}),
            InstrumentFamily.EQUITY,
        )
        spec = spec_for_symbol("QQQ", metadata={"instrument_type": "etf", "venue": "NASDAQ"})
        self.assertEqual(spec.family, InstrumentFamily.EQUITY)
        self.assertTrue(spec.is_etf)

    def test_short_blocked_when_not_locatable(self) -> None:
        hard = spec_for_symbol(
            "HARD",
            metadata={
                "supports_short": True,
                "borrow": BorrowConstraints(locatable=False),
            },
        )
        policy = ShortMarginPolicy(initial_margin_pct=50, maintenance_margin_pct=30)
        ok, reason, qty = validate_intent_rules(
            spec=hard, side="sell", qty=10, price=50, opening_short=True, short_margin_policy=policy
        )
        self.assertFalse(ok)
        self.assertIn("BORROW_CONSTRAINT", reason)
        self.assertEqual(qty, Decimal("10"))

    def test_htb_requires_measured_borrow_fee(self) -> None:
        htb = spec_for_symbol(
            "HTB",
            metadata={
                "supports_short": True,
                "borrow": BorrowConstraints(locatable=True, hard_to_borrow=True),
            },
        )
        policy = ShortMarginPolicy(initial_margin_pct=50, maintenance_margin_pct=30)
        ok, reason, _ = validate_intent_rules(
            spec=htb, side="sell", qty=10, price=50, opening_short=True, short_margin_policy=policy
        )
        self.assertFalse(ok)
        self.assertIn("hard-to-borrow", reason)

        policy2 = ShortMarginPolicy(
            initial_margin_pct=50, maintenance_margin_pct=30, borrow_fee_bps_per_day=25.0
        )
        ok2, reason2, qty2 = validate_intent_rules(
            spec=htb, side="sell", qty=10, price=50, opening_short=True, short_margin_policy=policy2
        )
        self.assertTrue(ok2, reason2)
        self.assertEqual(qty2, Decimal("10"))

    def test_short_allowed_locatable_with_margin(self) -> None:
        policy = ShortMarginPolicy(initial_margin_pct=50, maintenance_margin_pct=30)
        spy_short = InstrumentSpec(
            instrument_id="equity:SPY:ARCA",
            symbol="SPY",
            family=InstrumentFamily.EQUITY,
            venue="ARCA",
            quote_currency="USD",
            lot_size="1",
            tick_size="0.01",
            min_notional="1",
            supports_short=True,
            is_etf=True,
            borrow=BorrowConstraints(locatable=True),
        )
        ok, reason, qty = validate_intent_rules(
            spec=spy_short,
            side="sell",
            qty=5,
            price=400,
            opening_short=True,
            short_margin_policy=policy,
        )
        self.assertTrue(ok, reason)
        self.assertEqual(qty, Decimal("5"))

    def test_session_calendar_hook(self) -> None:
        uni = PointInTimeUniverse(
            calendar=[
                SessionCalendarDay(date="2024-07-04", session="holiday", exchange="ARCA"),
                SessionCalendarDay(date="2024-07-05", session="open", exchange="ARCA"),
            ]
        )
        closed = equity_session_is_open(EQUITY_SPY, "2024-07-04", universe=uni)
        opened = equity_session_is_open(EQUITY_SPY, "2024-07-05", universe=uni)
        self.assertFalse(closed["isOpen"])
        self.assertTrue(opened["isOpen"])
        missing = equity_session_is_open(EQUITY_SPY, "2024-07-06")
        self.assertTrue(missing["isOpen"])
        self.assertEqual(missing["status"], "UNMEASURED")

    def test_adjustment_mode_labelled(self) -> None:
        self.assertEqual(EQUITY_AAPL.normalized_adjustment_mode(), "as_traded")
        spec = spec_for_symbol("AAPL", metadata={"adjustment_mode": "split_adjusted"})
        self.assertEqual(spec.public_dict()["adjustment_mode"], "split_adjusted")
        bad = spec_for_symbol("AAPL", metadata={"adjustment_mode": "magic"})
        self.assertEqual(bad.normalized_adjustment_mode(), "unknown")

    def test_borrow_cost_status(self) -> None:
        unmeasured = BorrowConstraints(locatable=True)
        self.assertEqual(unmeasured.resolved_status(), "UNMEASURED")
        measured = BorrowConstraints(locatable=True, borrow_fee_bps_per_day=12.5)
        self.assertEqual(measured.resolved_status(), "MEASURED")
        self.assertEqual(measured.public_dict()["borrowCost"], "MEASURED")


if __name__ == "__main__":
    unittest.main()
