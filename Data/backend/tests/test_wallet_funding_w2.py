"""Paper wallet funding — capital contribution/withdrawal ≠ trading PnL."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from Data.modules.market_sim.accounting import WalletLedger, money
from Data.modules.market_sim.portefeuille.ledger import PortfolioBook
from Data.modules.market_sim.types import MarketSimError


class WalletLedgerFundingTests(unittest.TestCase):
    def test_top_up_does_not_change_realized_pnl(self) -> None:
        w = WalletLedger(wallet_id="w1", owner_id="a1", owner_kind="agent", cash=money(10_000))
        w.realized_pnl = money(250)
        before = w.realized_pnl
        out = w.apply_funding(
            delta=5_000,
            tx_id="fund-1",
            reason="operator top-up",
            operator_id="op-1",
            kind="TOP_UP",
        )
        self.assertTrue(out["applied"])
        self.assertEqual(w.cash, money(15_000))
        self.assertEqual(w.realized_pnl, before)
        self.assertTrue(out["realized_pnl_unchanged"])

    def test_withdrawal_refuses_when_reserved(self) -> None:
        w = WalletLedger(wallet_id="w1", owner_id="a1", owner_kind="agent", cash=money(10_000))
        w.reserved_cash = money(8_000)
        with self.assertRaises(ValueError):
            w.apply_funding(delta=-5_000, tx_id="fund-2", reason="withdraw", kind="WITHDRAWAL")

    def test_idempotent_funding(self) -> None:
        w = WalletLedger(wallet_id="w1", owner_id="a1", owner_kind="agent", cash=money(1_000))
        a = w.apply_funding(delta=100, tx_id="same", reason="once")
        b = w.apply_funding(delta=100, tx_id="same", reason="once")
        self.assertTrue(a["applied"])
        self.assertFalse(b["applied"])
        self.assertEqual(b["reason"], "duplicate_tx_id")
        self.assertEqual(w.cash, money(1_100))


class PortfolioBookFundingTests(unittest.TestCase):
    def test_funding_preserves_realized_pnl(self) -> None:
        book = PortfolioBook(portfolio_id="p1", cash=money(50_000))
        book.realized_pnl = money(1_234)
        out = book.apply_funding(delta=10_000, tx_id="pf-1", reason="top-up")
        self.assertTrue(out["applied"])
        self.assertEqual(book.cash, money(60_000))
        self.assertEqual(book.realized_pnl, money(1_234))
        self.assertEqual(len(book.funding_events), 1)


class PortfolioServiceFundingTests(unittest.TestCase):
    def test_fund_portfolio_end_to_end(self) -> None:
        from unittest.mock import MagicMock

        from Data.modules.market_sim.data_store import MarketDataStore
        from Data.modules.market_sim.service import MarketSimControlPlane
        from Data.modules.market_sim.store import MarketSimStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            provider = MagicMock()
            provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
            provider.fetch_quote.side_effect = lambda symbol: {
                "price": 100.0,
                "symbol": symbol,
            }
            plane.providers = MagicMock()
            plane.providers.get.return_value = provider

            pf = plane.create_portfolio(
                name="Funding Test",
                initial_equity=100_000.0,
                orchestra_id=None,
                settings={"allow_manual_only": True},
            )
            pid = pf["portfolio_id"]
            realized_before = Decimal(str(pf.get("realized_pnl") or "0"))
            key = f"idem-{uuid.uuid4()}"
            result = plane.fund_portfolio(
                pid,
                delta=25_000.0,
                reason="Wave2 operator paper top-up",
                idempotency_key=key,
                operator_id="test-op",
                kind="TOP_UP",
            )
            self.assertTrue(result["funding"]["applied"])
            self.assertTrue(result["truth"]["funding_is_not_pnl"])
            after = result["portfolio"]
            self.assertEqual(Decimal(str(after["cash"])), Decimal("125000"))
            self.assertEqual(Decimal(str(after.get("realized_pnl") or "0")), realized_before)

            again = plane.fund_portfolio(
                pid,
                delta=25_000.0,
                reason="Wave2 operator paper top-up",
                idempotency_key=key,
                operator_id="test-op",
            )
            self.assertFalse(again["funding"]["applied"])
            self.assertEqual(Decimal(str(again["portfolio"]["cash"])), Decimal("125000"))


if __name__ == "__main__":
    unittest.main()
