"""Risk engine: the veto is deterministic and cannot be argued away.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.accounting import Portfolio
from trading_lab.adapters import adapter_for
from trading_lab.contracts import InstrumentSpec, MarketEvent, OrderIntent, RiskLimits
from trading_lab.risk import RiskContext, RiskEngine, correlation_groups_from_specs, sanitize_model_risk_payload

PERP = InstrumentSpec(
    instrument_id="crypto_perpetual:test:BTCUSDT",
    family="crypto_perpetual",
    venue="test",
    symbol="BTCUSDT",
    base_currency="BTC",
    quote_currency="USDT",
    settlement_currency="USDT",
    tick_size=Decimal("0.1"),
    lot_size=Decimal("0.001"),
    initial_margin_rate=Decimal("0.1"),
    maintenance_margin_rate=Decimal("0.05"),
    funding_interval_hours=8,
)

EVENT = MarketEvent(
    instrument_id=PERP.instrument_id,
    timeframe="1h",
    event_time="2020-01-01T00:00:00+00:00",
    available_at="2020-01-01T00:00:00+00:00",
    open=100.0,
    high=101.0,
    low=99.0,
    close=100.0,
    volume=1000.0,
)


def intent(**overrides) -> OrderIntent:
    payload = {
        "intent_id": "i1",
        "instrument_id": PERP.instrument_id,
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def context(**overrides) -> RiskContext:
    values = {
        "event": EVENT,
        "equity": Decimal("100000"),
        "peak_equity": Decimal("100000"),
    }
    values.update(overrides)
    return RiskContext(**values)


class RiskEngineTest(unittest.TestCase):
    def evaluate(self, engine: RiskEngine, order: OrderIntent, *, portfolio: Portfolio | None = None, ctx: RiskContext | None = None):
        return engine.evaluate(
            order,
            spec=PERP,
            adapter=adapter_for(PERP),
            portfolio=portfolio or Portfolio(base_currency="USDT", starting_cash={"USDT": Decimal("100000")}),
            context=ctx or context(),
        )

    def test_a_normal_order_is_allowed(self) -> None:
        decision = self.evaluate(RiskEngine(RiskLimits()), intent())
        self.assertEqual(decision.decision, "allow")
        self.assertGreater(decision.approved_quantity, Decimal("0"))

    def test_order_notional_limit_reduces_instead_of_silently_passing(self) -> None:
        engine = RiskEngine(RiskLimits(max_order_notional=Decimal("50")))
        decision = self.evaluate(engine, intent(quantity=Decimal("10")))
        self.assertIn(decision.decision, {"allow_reduced", "block"})
        if decision.decision == "allow_reduced":
            self.assertLess(decision.approved_quantity, Decimal("10"))
            self.assertTrue(decision.reasons)

    def test_kill_switch_blocks_new_exposure(self) -> None:
        engine = RiskEngine(RiskLimits(kill_switch_armed=True))
        decision = self.evaluate(engine, intent())
        self.assertEqual(decision.decision, "block")
        self.assertIn("kill_switch_blocks_new_exposure", decision.reasons)

    def test_kill_switch_still_allows_closing_a_position(self) -> None:
        portfolio = Portfolio(base_currency="USDT", starting_cash={"USDT": Decimal("100000")})
        position = portfolio.ensure_position(PERP, "margin")
        position.signed_quantity = Decimal("1")
        position.average_price = Decimal("100")
        engine = RiskEngine(RiskLimits(kill_switch_armed=True))
        decision = self.evaluate(engine, intent(side="sell", reduce_only=True), portfolio=portfolio)
        self.assertNotEqual(decision.decision, "block")

    def test_model_supplied_override_fields_are_refused(self) -> None:
        engine = RiskEngine(RiskLimits())
        decision = self.evaluate(engine, intent(metadata={"override_limits": True}))
        self.assertEqual(decision.decision, "block")
        self.assertTrue(any("override_attempt_rejected" in reason for reason in decision.reasons))

    def test_sanitizer_strips_override_keys_before_they_reach_the_engine(self) -> None:
        clean, stripped = sanitize_model_risk_payload(
            {"rationale": "trend is up", "force_execute": True, "bypass_risk": 1}
        )
        self.assertNotIn("force_execute", clean)
        self.assertNotIn("bypass_risk", clean)
        self.assertIn("rationale", clean)
        self.assertEqual(sorted(stripped), ["bypass_risk", "force_execute"])

    def test_drawdown_limit_blocks_new_risk(self) -> None:
        engine = RiskEngine(RiskLimits(max_drawdown_fraction=Decimal("0.1")))
        decision = self.evaluate(
            engine,
            intent(),
            ctx=context(equity=Decimal("80000"), peak_equity=Decimal("100000")),
        )
        self.assertEqual(decision.decision, "block")

    def test_incomplete_data_blocks_new_exposure(self) -> None:
        engine = RiskEngine(RiskLimits())
        decision = self.evaluate(engine, intent(), ctx=context(data_complete=False))
        self.assertEqual(decision.decision, "block")
        self.assertIn("incomplete_market_data_blocks_new_exposure", decision.reasons)

    def test_open_order_ceiling_is_enforced(self) -> None:
        engine = RiskEngine(RiskLimits(max_open_orders=2))
        decision = self.evaluate(engine, intent(), ctx=context(open_order_count=2))
        self.assertEqual(decision.decision, "block")

    def test_decisions_are_reproducible(self) -> None:
        engine = RiskEngine(RiskLimits())
        first = self.evaluate(engine, intent())
        second = self.evaluate(engine, intent())
        self.assertEqual(first.decision, second.decision)
        self.assertEqual(first.approved_quantity, second.approved_quantity)

    def test_correlation_groups_are_derived_from_instrument_facts(self) -> None:
        groups = correlation_groups_from_specs([PERP])
        self.assertIn(PERP.instrument_id, groups)
        self.assertTrue(groups[PERP.instrument_id])


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
