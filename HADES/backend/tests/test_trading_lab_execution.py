"""Exchange simulator: order lifecycle, fill timing, costs and refusals.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.contracts import CostModel, InstrumentSpec, MarketEvent, OrderIntent
from trading_lab.execution import ExchangeSimulator

SPOT = InstrumentSpec(
    instrument_id="crypto_spot:test:BTCUSDT",
    family="crypto_spot",
    venue="test",
    symbol="BTCUSDT",
    base_currency="BTC",
    quote_currency="USDT",
    tick_size=Decimal("0.01"),
    lot_size=Decimal("0.001"),
)

FREE = CostModel(
    taker_fee_bps=Decimal("0"),
    maker_fee_bps=Decimal("0"),
    half_spread_bps=Decimal("0"),
    slippage_bps=Decimal("0"),
    max_volume_participation=Decimal("1"),
)


def bar(event_time: str, *, open_: float, high: float, low: float, close: float, volume: float = 1000.0) -> MarketEvent:
    return MarketEvent(
        instrument_id=SPOT.instrument_id,
        timeframe="1h",
        event_time=event_time,
        available_at=event_time,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def intent(**overrides) -> OrderIntent:
    payload = {
        "intent_id": "i1",
        "instrument_id": SPOT.instrument_id,
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


class ExecutionTimingTest(unittest.TestCase):
    def test_an_order_never_fills_on_the_event_that_created_it(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        signal_bar = bar("2020-01-01T00:00:00+00:00", open_=100, high=101, low=99, close=100)
        simulator.submit(intent(), SPOT, eligible_from=signal_bar.available_at, now=signal_bar.event_time)
        same = simulator.process_event(signal_bar)
        self.assertEqual(same.fills, [], "the bar that produced the signal may not also fill the order")

        next_bar = bar("2020-01-01T01:00:00+00:00", open_=102, high=103, low=101, close=102)
        later = simulator.process_event(next_bar)
        self.assertEqual(len(later.fills), 1)
        self.assertEqual(later.fills[0].price, Decimal("102"), "a market order fills at the next open")

    def test_costs_move_the_price_against_the_taker(self) -> None:
        simulator = ExchangeSimulator(
            cost_model=CostModel(half_spread_bps=Decimal("10"), slippage_bps=Decimal("0"), taker_fee_bps=Decimal("0"))
        )
        simulator.submit(intent(), SPOT, eligible_from="2020-01-01T00:00:00+00:00", now="2020-01-01T00:00:00+00:00")
        outcome = simulator.process_event(bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=99, close=100))
        self.assertGreater(outcome.fills[0].price, Decimal("100"), "a buyer pays the offer, not the mid")

    def test_limit_order_fills_at_its_own_price_not_at_the_candle_low(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        simulator.submit(
            intent(order_type="limit", limit_price=Decimal("99")),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=95, close=100))
        self.assertEqual(outcome.fills[0].price, Decimal("99"))

    def test_unreachable_limit_does_not_fill(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        simulator.submit(
            intent(order_type="limit", limit_price=Decimal("90")),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=99, close=100))
        self.assertEqual(outcome.fills, [])

    def test_stop_does_not_fill_at_the_stop_when_the_market_gapped_through_it(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        simulator.submit(
            intent(side="sell", order_type="stop_market", stop_price=Decimal("95")),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(bar("2020-01-01T01:00:00+00:00", open_=80, high=85, low=78, close=80))
        self.assertEqual(outcome.fills[0].price, Decimal("80"), "the gap price is worse than the stop and must be used")

    def test_volume_participation_produces_a_partial_fill(self) -> None:
        simulator = ExchangeSimulator(cost_model=CostModel(max_volume_participation=Decimal("0.1")))
        simulator.submit(
            intent(quantity=Decimal("100")),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(
            bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=99, close=100, volume=100)
        )
        self.assertEqual(outcome.fills[0].quantity, Decimal("10"))
        order = outcome.touched_orders[0]
        self.assertEqual(order.status, "partially_filled")

    def test_post_only_is_cancelled_instead_of_crossing(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        simulator.submit(
            intent(order_type="limit", limit_price=Decimal("105"), post_only=True),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(bar("2020-01-01T01:00:00+00:00", open_=100, high=106, low=99, close=100))
        self.assertEqual(outcome.fills, [])
        self.assertEqual(outcome.touched_orders[0].reject_reason, "post_only_would_cross")

    def test_ioc_remainder_is_cancelled_on_the_same_event(self) -> None:
        simulator = ExchangeSimulator(cost_model=CostModel(max_volume_participation=Decimal("0.1")))
        simulator.submit(
            intent(quantity=Decimal("100"), time_in_force="IOC"),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(
            bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=99, close=100, volume=100)
        )
        self.assertEqual(outcome.touched_orders[0].status, "cancelled")
        self.assertEqual(outcome.touched_orders[0].reject_reason, "ioc_remainder_cancelled")

    def test_fok_refuses_a_partial_fill_entirely(self) -> None:
        simulator = ExchangeSimulator(cost_model=CostModel(max_volume_participation=Decimal("0.1")))
        simulator.submit(
            intent(quantity=Decimal("100"), time_in_force="FOK"),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        outcome = simulator.process_event(
            bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=99, close=100, volume=100)
        )
        self.assertEqual(outcome.fills, [])
        self.assertEqual(outcome.touched_orders[0].reject_reason, "fok_insufficient_liquidity")

    def test_reduce_only_without_a_position_is_refused_at_submission(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        outcome = simulator.submit(
            intent(side="sell", reduce_only=True),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
            position_quantity=Decimal("0"),
        )
        self.assertEqual(outcome.touched_orders[0].status, "rejected")
        self.assertEqual(outcome.touched_orders[0].reject_reason, "reduce_only_with_no_position")

    def test_quantity_below_lot_size_is_refused(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        outcome = simulator.submit(
            intent(quantity=Decimal("0.0001")),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        self.assertEqual(outcome.touched_orders[0].status, "rejected")
        self.assertIn("lot_size", outcome.touched_orders[0].reject_reason)

    def test_bracket_exits_are_mutually_exclusive(self) -> None:
        simulator = ExchangeSimulator(cost_model=FREE)
        simulator.submit(
            intent(
                order_type="bracket",
                take_profit_price=Decimal("110"),
                stop_loss_price=Decimal("90"),
            ),
            SPOT,
            eligible_from="2020-01-01T00:00:00+00:00",
            now="2020-01-01T00:00:00+00:00",
        )
        children = [order for order in simulator.orders.values() if order.intent.order_type != "bracket"]
        self.assertEqual(len(children), 2, "a bracket registers a take-profit and a stop child")
        groups = {order.oco_group for order in children}
        self.assertEqual(len(groups), 1, "both children share one OCO group")

    def test_fills_are_deterministic_across_identical_runs(self) -> None:
        def run() -> list[tuple[str, Decimal, Decimal]]:
            simulator = ExchangeSimulator(cost_model=FREE)
            simulator.submit(intent(), SPOT, eligible_from="2020-01-01T00:00:00+00:00", now="2020-01-01T00:00:00+00:00")
            outcome = simulator.process_event(bar("2020-01-01T01:00:00+00:00", open_=100, high=101, low=99, close=100))
            return [(item.event_id, item.quantity, item.price) for item in outcome.fills]

        self.assertEqual(run(), run(), "the same inputs must produce the same fill ids and prices")


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
