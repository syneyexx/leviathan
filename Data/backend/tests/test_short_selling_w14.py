"""Wave 14 — short-selling semantic consistency (NextBarFillModel + accounting)."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.accounting import WalletBook, WalletLedger, money
from Data.modules.market_sim.execution import NextBarFillModel, make_intent
from Data.modules.market_sim.instruments import (
    BorrowConstraints,
    InstrumentFamily,
    InstrumentSpec,
)
from Data.modules.market_sim.risk_guard import RiskGuard, RiskLimits
from Data.modules.market_sim.short_margin import ShortMarginPolicy


def _spec(*, supports_short: bool = True, borrow: BorrowConstraints | None = None) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id="equity:XYZ:X",
        symbol="XYZ",
        family=InstrumentFamily.EQUITY,
        venue="X",
        quote_currency="USD",
        supports_short=supports_short,
        lot_size="1",
        tick_size="0.01",
        min_notional="1",
        borrow=borrow,
    )


def _policy(**kw) -> ShortMarginPolicy:
    return ShortMarginPolicy(
        initial_margin_pct=kw.get("initial_margin_pct", 50.0),
        maintenance_margin_pct=kw.get("maintenance_margin_pct", 30.0),
        borrow_fee_bps_per_day=kw.get("borrow_fee_bps_per_day"),
    )


def _wallet(*, cash: float = 100_000, shorting: bool = True, policy: ShortMarginPolicy | None = None) -> WalletLedger:
    w = WalletBook().ensure_agent("a", initial_cash=cash)
    w.shorting_enabled = shorting
    w.short_margin_policy = policy or _policy()
    return w


def _model() -> NextBarFillModel:
    return NextBarFillModel(fee_bps=10.0, slippage_bps=0.0, max_participation=1.0)


class ShortSellingW14Tests(unittest.TestCase):
    def test_open_short(self) -> None:
        w = _wallet()
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=10,
            decision_bar_index=0, decision_ts="t", info_version="v",
        )
        fill = _model().execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertTrue(fill.filled, fill.detail)
        self.assertEqual(float(w.position_qty), -10.0)
        self.assertEqual(float(w.avg_entry), 100.0)
        self.assertGreater(float(w.cash), 100_000)  # proceeds credited
        self.assertGreater(float(w.margin_used), 0)
        self.assertIn(w.borrow_cost_status, {"UNMEASURED", "ASSUMED", "MEASURED"})

    def test_add_short(self) -> None:
        w = _wallet()
        m = _model()
        for i, qty in enumerate((5, 5)):
            intent = make_intent(
                run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=qty,
                decision_bar_index=i, decision_ts="t", info_version=f"v{i}",
            )
            fill = m.execute_intent(
                wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=i + 1
            )
            self.assertTrue(fill.filled, fill.detail)
        self.assertEqual(float(w.position_qty), -10.0)

    def test_partial_cover(self) -> None:
        w = _wallet()
        m = _model()
        open_i = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=10,
            decision_bar_index=0, decision_ts="t", info_version="v0",
        )
        self.assertTrue(
            m.execute_intent(
                wallet=w, intent=open_i, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
            ).filled
        )
        cover = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="BUY", qty=4,
            decision_bar_index=1, decision_ts="t", info_version="v1",
        )
        fill = m.execute_intent(
            wallet=w, intent=cover, fill_open=90.0, bar_volume=1e9, fill_bar_index=2
        )
        self.assertTrue(fill.filled, fill.detail)
        self.assertEqual(float(w.position_qty), -6.0)
        self.assertGreater(float(w.realized_pnl), 0)  # covered below entry

    def test_full_cover(self) -> None:
        w = _wallet()
        m = _model()
        open_i = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=10,
            decision_bar_index=0, decision_ts="t", info_version="v0",
        )
        m.execute_intent(wallet=w, intent=open_i, fill_open=100.0, bar_volume=1e9, fill_bar_index=1)
        cover = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="BUY", qty=10,
            decision_bar_index=1, decision_ts="t", info_version="v1",
        )
        fill = m.execute_intent(
            wallet=w, intent=cover, fill_open=95.0, bar_volume=1e9, fill_bar_index=2
        )
        self.assertTrue(fill.filled, fill.detail)
        self.assertEqual(float(w.position_qty), 0.0)
        self.assertGreater(float(w.realized_pnl), 0)
        self.assertEqual(float(w.margin_used), 0.0)

    def test_attempt_reversal_fails_closed(self) -> None:
        w = _wallet()
        w.allow_position_reversal = False
        m = _model()
        open_i = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=5,
            decision_bar_index=0, decision_ts="t", info_version="v0",
        )
        m.execute_intent(wallet=w, intent=open_i, fill_open=100.0, bar_volume=1e9, fill_bar_index=1)
        rev = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="BUY", qty=10,
            decision_bar_index=1, decision_ts="t", info_version="v1",
            metadata={"allow_position_reversal": False},
        )
        fill = m.execute_intent(
            wallet=w, intent=rev, fill_open=100.0, bar_volume=1e9, fill_bar_index=2
        )
        # Caps to cover only — never opens long by default
        self.assertTrue(fill.filled, fill.detail)
        self.assertEqual(float(w.position_qty), 0.0)

        # Explicit oversize with FOK-style rejection via ledger when not capped
        w2 = _wallet()
        w2.allow_position_reversal = False
        open2 = make_intent(
            run_id="r", agent_id="a", wallet_id=w2.wallet_id, side="SELL", qty=5,
            decision_bar_index=0, decision_ts="t", info_version="x0",
        )
        m.execute_intent(wallet=w2, intent=open2, fill_open=100.0, bar_volume=1e9, fill_bar_index=1)
        with self.assertRaises(ValueError) as ctx:
            w2.apply_buy(
                qty=10, price=100, fee=0, tx_id="rev-fail",
                meta={"allow_position_reversal": False},
            )
        self.assertIn("POSITION_REVERSAL_BLOCKED", str(ctx.exception))

    def test_fees_and_pnl(self) -> None:
        w = _wallet()
        m = NextBarFillModel(fee_bps=100.0, slippage_bps=0.0, max_participation=1.0)  # 1%
        open_i = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=10,
            decision_bar_index=0, decision_ts="t", info_version="v0",
        )
        m.execute_intent(wallet=w, intent=open_i, fill_open=100.0, bar_volume=1e9, fill_bar_index=1)
        fees_after_open = float(w.fees_paid)
        self.assertAlmostEqual(fees_after_open, 10.0, places=4)  # 1% of 1000
        # Unrealized: price rises → short loses
        upnl = float(w.unrealized_pnl(110.0))
        self.assertLess(upnl, 0)
        cover = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="BUY", qty=10,
            decision_bar_index=1, decision_ts="t", info_version="v1",
        )
        m.execute_intent(wallet=w, intent=cover, fill_open=90.0, bar_volume=1e9, fill_bar_index=2)
        self.assertGreater(float(w.fees_paid), fees_after_open)
        self.assertGreater(float(w.realized_pnl), 0)

    def test_margin_block(self) -> None:
        # Tiny cash cannot support large short margin
        w = _wallet(cash=100.0, policy=_policy(initial_margin_pct=50.0))
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=100,
            decision_bar_index=0, decision_ts="t", info_version="v",
        )
        fill = _model().execute_intent(
            wallet=w, intent=intent, fill_open=100.0, bar_volume=1e9, fill_bar_index=1
        )
        self.assertFalse(fill.filled)
        self.assertIn("margin", fill.detail.lower())

    def test_borrow_unavailable(self) -> None:
        borrow = BorrowConstraints(locatable=False, hard_to_borrow=True)
        spec = _spec(supports_short=True, borrow=borrow)
        guard = RiskGuard(
            RiskLimits(),
            instrument_spec=spec,
            short_margin_policy=_policy(),
        )
        w = _wallet()
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=1,
            decision_bar_index=0, decision_ts="t", info_version="v",
        )
        d = guard.evaluate_intent(intent, wallet=w, price=100.0)
        self.assertFalse(d.allowed)
        self.assertIn("BORROW", d.reason)

    def test_instrument_disallows(self) -> None:
        guard = RiskGuard(
            RiskLimits(),
            instrument_spec=_spec(supports_short=False),
            short_margin_policy=_policy(),
        )
        w = _wallet()
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=1,
            decision_bar_index=0, decision_ts="t", info_version="v",
        )
        d = guard.evaluate_intent(intent, wallet=w, price=100.0)
        self.assertFalse(d.allowed)
        self.assertIn("INSTRUMENT_RULE", d.reason)

    def test_portfolio_disallows(self) -> None:
        guard = RiskGuard(
            RiskLimits(),
            instrument_spec=_spec(supports_short=True),
            short_margin_policy=_policy(),
            portfolio_shorting_enabled=False,
        )
        w = _wallet()
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=1,
            decision_bar_index=0, decision_ts="t", info_version="v",
        )
        d = guard.evaluate_intent(intent, wallet=w, price=100.0)
        self.assertFalse(d.allowed)
        self.assertIn("PORTFOLIO_SHORTING_DISABLED", d.reason)

    def test_crash_replay_restores_short(self) -> None:
        w = _wallet(policy=_policy(borrow_fee_bps_per_day=None))
        intent = make_intent(
            run_id="r", agent_id="a", wallet_id=w.wallet_id, side="SELL", qty=7,
            decision_bar_index=0, decision_ts="t", info_version="v",
        )
        self.assertTrue(
            _model().execute_intent(
                wallet=w, intent=intent, fill_open=50.0, bar_volume=1e9, fill_bar_index=1
            ).filled
        )
        snap = w.public_dict(50.0)
        self.assertEqual(snap["borrow_cost_status"], "UNMEASURED")
        restored = WalletLedger.from_public_dict(snap)
        self.assertEqual(float(restored.position_qty), -7.0)
        self.assertEqual(float(restored.avg_entry), 50.0)
        self.assertTrue(restored.shorting_enabled)
        self.assertEqual(restored.borrow_cost_status, "UNMEASURED")

    def test_capability_honesty_paper_feature_gated(self) -> None:
        from Data.modules.market_sim.capabilities import execution_granularity_matrix

        rows = execution_granularity_matrix()
        ohlcv = next(r for r in rows if r["granularity"] == "BAR_OHLCV")
        short = ohlcv["short_selling"]
        self.assertEqual(short["historical_sim"], "MEASURED")
        self.assertEqual(short["paper"], "FEATURE_GATED")
        self.assertTrue(short["truth"]["paper_not_advertised_as_fully_supported"])


if __name__ == "__main__":
    unittest.main()
