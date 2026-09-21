"""Ledger correctness: Decimal money, idempotent bookings and honest valuation.

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
from trading_lab.contracts import FillEvent, InstrumentSpec

SPOT = InstrumentSpec(
    instrument_id="crypto_spot:test:BTCUSDT",
    family="crypto_spot",
    venue="test",
    symbol="BTCUSDT",
    base_currency="BTC",
    quote_currency="USDT",
    tick_size=Decimal("0.01"),
    lot_size=Decimal("0.00001"),
)


def fill(event_id: str, side: str, quantity: str, price: str, *, fee: str = "0") -> FillEvent:
    return FillEvent(
        event_id=event_id,
        order_id=f"order_{event_id}",
        instrument_id=SPOT.instrument_id,
        event_time="2020-01-01T00:00:00+00:00",
        side=side,  # type: ignore[arg-type]
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        fee_currency="USDT",
    )


class LedgerTest(unittest.TestCase):
    def portfolio(self) -> Portfolio:
        return Portfolio(base_currency="USDT", starting_cash={"USDT": Decimal("10000")})

    def test_money_stays_exact_under_repeated_fractional_fills(self) -> None:
        portfolio = self.portfolio()
        for index in range(10):
            portfolio.apply_fill(
                fill(f"f{index}", "buy", "0.1", "0.1"), SPOT, settlement_style="funded"
            )
        # Ten purchases of 0.1 @ 0.1 cost exactly 0.10, not 0.09999999999999999.
        self.assertEqual(portfolio.balance("USDT"), Decimal("9999.90"))

    def test_replaying_the_same_fill_books_nothing_twice(self) -> None:
        portfolio = self.portfolio()
        first = portfolio.apply_fill(fill("f1", "buy", "1", "100"), SPOT, settlement_style="funded")
        second = portfolio.apply_fill(fill("f1", "buy", "1", "100"), SPOT, settlement_style="funded")
        self.assertTrue(first)
        self.assertEqual(second, [], "a replayed fill must not double-book")
        self.assertEqual(portfolio.balance("USDT"), Decimal("9900"))
        self.assertEqual(portfolio.position(SPOT.instrument_id).signed_quantity, Decimal("1"))

    def test_realised_pnl_uses_weighted_average_cost(self) -> None:
        portfolio = self.portfolio()
        portfolio.apply_fill(fill("f1", "buy", "1", "100"), SPOT, settlement_style="funded")
        portfolio.apply_fill(fill("f2", "buy", "1", "200"), SPOT, settlement_style="funded")
        portfolio.apply_fill(fill("f3", "sell", "1", "200"), SPOT, settlement_style="funded")
        position = portfolio.position(SPOT.instrument_id)
        self.assertEqual(position.average_price, Decimal("150"))
        self.assertEqual(portfolio.realized_pnl, Decimal("50"))

    def test_fees_are_booked_to_cash_and_to_a_fee_account(self) -> None:
        portfolio = self.portfolio()
        portfolio.apply_fill(fill("f1", "buy", "1", "100", fee="0.25"), SPOT, settlement_style="funded")
        self.assertEqual(portfolio.fees_paid, Decimal("0.25"))
        self.assertEqual(portfolio.balance("USDT"), Decimal("9899.75"))
        accounts = {entry.account for entry in portfolio.entries}
        self.assertIn("fees", accounts)

    def test_cash_flows_are_idempotent_as_well(self) -> None:
        portfolio = self.portfolio()
        portfolio.apply_cash_flow(
            source_event_id="funding-1",
            event_time="2020-01-01T08:00:00+00:00",
            currency="USDT",
            amount=Decimal("-1.5"),
            kind="funding",
        )
        portfolio.apply_cash_flow(
            source_event_id="funding-1",
            event_time="2020-01-01T08:00:00+00:00",
            currency="USDT",
            amount=Decimal("-1.5"),
            kind="funding",
        )
        self.assertEqual(portfolio.balance("USDT"), Decimal("9998.5"))

    def test_equity_reports_a_warning_instead_of_inventing_a_rate(self) -> None:
        portfolio = Portfolio(base_currency="USD", starting_cash={"USD": Decimal("100"), "JPY": Decimal("1000")})
        equity, warnings = portfolio.equity()
        self.assertEqual(equity, Decimal("100"), "an unconvertible currency must not be silently added")
        self.assertTrue(any("JPY" in warning for warning in warnings))

    def test_reconciliation_detects_a_consistent_book(self) -> None:
        portfolio = self.portfolio()
        portfolio.apply_fill(fill("f1", "buy", "1", "100", fee="0.1"), SPOT, settlement_style="funded")
        portfolio.mark(SPOT.instrument_id, Decimal("110"), "2020-01-01T01:00:00+00:00")
        report = portfolio.reconcile()
        self.assertTrue(report["ok"], report["mismatches"])

    def test_state_round_trip_restores_positions_and_cash(self) -> None:
        portfolio = self.portfolio()
        portfolio.apply_fill(fill("f1", "buy", "2", "100"), SPOT, settlement_style="funded")
        restored = Portfolio.restore(portfolio.state())
        self.assertEqual(restored.balance("USDT"), portfolio.balance("USDT"))
        self.assertEqual(
            restored.position(SPOT.instrument_id).signed_quantity,
            portfolio.position(SPOT.instrument_id).signed_quantity,
        )
        self.assertTrue(restored.already_applied("f1"), "replay protection must survive a restart")


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
