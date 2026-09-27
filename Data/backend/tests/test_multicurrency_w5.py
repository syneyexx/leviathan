"""Multi-currency valuation fail-closed tests (Wave 5)."""

from __future__ import annotations

import unittest
from decimal import Decimal

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.institutional_core.moneyutil import convert
from Data.modules.market_sim.portefeuille.ledger import PortfolioBook, PositionState


class MultiCurrencyTests(unittest.TestCase):
    def test_missing_fx_blocks(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            convert(100, from_currency="EUR", to_currency="USD", fx_rate=None)
        self.assertIn("missing FX", str(ctx.exception))

    def test_multicurrency_nav_explicit_fx(self) -> None:
        usd = convert(100, from_currency="EUR", to_currency="USD", fx_rate="1.10")
        self.assertEqual(usd.currency, "USD")
        self.assertEqual(usd.amount, money("110"))

    def test_portefeuille_blocks_currency_mismatch(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=Decimal("100000"), currency="USD")
        book.positions["EURUSD"] = PositionState(
            symbol="EURUSD",
            side="LONG",
            qty=Decimal("10"),
            avg_entry=Decimal("1.10"),
        )
        with self.assertRaises(ValueError) as ctx:
            book.equity({"EURUSD": Decimal("1.12")}, quote_currencies={"EURUSD": "EUR"})
        self.assertIn("VALUATION_BLOCKED", str(ctx.exception))

    def test_wallet_single_currency_refuses_mix(self) -> None:
        w = WalletLedger(
            wallet_id="w1",
            owner_id="t",
            owner_kind="agent",
            cash=Decimal("1000"),
            currency="USD",
        )
        with self.assertRaises(ValueError):
            w._assert_currency("EUR")


if __name__ == "__main__":
    unittest.main()
