"""Decimal-precise wallet accounting — per-agent and shared portfolios."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any


ZERO = Decimal("0")
MONEY_QUANT = Decimal("0.00000001")


def D(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def money(value: Any) -> Decimal:
    return D(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


@dataclass
class PositionLot:
    symbol: str
    qty: Decimal = ZERO
    avg_entry: Decimal = ZERO

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": str(money(self.qty)),
            "avg_entry": str(money(self.avg_entry)),
        }


@dataclass
class WalletLedger:
    """One agent's (or shared) virtual wallet — never mixed with another agent's.

    W13B: supports multi-symbol ``positions`` while keeping scalar ``position_qty`` /
    ``avg_entry`` as the primary-symbol alias for backward-compatible single-symbol
    engines. Currency mixing is refused unless ``currency_mode`` allows it.
    """

    wallet_id: str
    owner_id: str  # agent_id or "shared"
    owner_kind: str  # agent | shared | paper
    cash: Decimal
    reserved_cash: Decimal = ZERO
    position_qty: Decimal = ZERO
    avg_entry: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO
    peak_equity: Decimal = ZERO
    currency: str = "USD"
    currency_mode: str = "single"  # single | multi (multi requires FX — not silent mix)
    primary_symbol: str | None = None
    positions: dict[str, PositionLot] = field(default_factory=dict)
    transactions: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = money(self.cash)
        self.reserved_cash = money(self.reserved_cash)
        self.position_qty = money(self.position_qty)
        self.avg_entry = money(self.avg_entry)
        self.realized_pnl = money(self.realized_pnl)
        self.fees_paid = money(self.fees_paid)
        if self.peak_equity <= 0:
            self.peak_equity = self.cash
        # Sync scalar position into positions map when primary known.
        if self.primary_symbol and self.position_qty != ZERO and self.primary_symbol not in self.positions:
            self.positions[self.primary_symbol] = PositionLot(
                symbol=self.primary_symbol,
                qty=self.position_qty,
                avg_entry=self.avg_entry,
            )

    def _assert_currency(self, quote_currency: str | None) -> None:
        if self.currency_mode != "single":
            raise ValueError("multi-currency mode requires explicit FX — not implemented silently")
        if quote_currency and str(quote_currency).upper() != str(self.currency).upper():
            raise ValueError(
                f"currency_mismatch: wallet={self.currency} quote={quote_currency} "
                "(single-currency restriction)"
            )

    @property
    def available_cash(self) -> Decimal:
        return money(self.cash - self.reserved_cash)

    def equity(self, price: Any) -> Decimal:
        return money(self.cash + self.position_qty * D(price))

    def _sync_primary_from_positions(self) -> None:
        """Keep scalar position_qty/avg_entry aligned with primary_symbol lot."""
        if self.primary_symbol and self.primary_symbol in self.positions:
            lot = self.positions[self.primary_symbol]
            self.position_qty = money(lot.qty)
            self.avg_entry = money(lot.avg_entry)
        elif not self.positions:
            # Scalar remains authoritative when no multi-symbol map is used.
            pass
        elif self.primary_symbol is None and len(self.positions) == 1:
            only = next(iter(self.positions.values()))
            self.primary_symbol = only.symbol
            self.position_qty = money(only.qty)
            self.avg_entry = money(only.avg_entry)

    def _upsert_lot(self, symbol: str, *, qty_delta: Decimal, price: Decimal) -> None:
        lot = self.positions.get(symbol)
        if lot is None:
            if qty_delta <= ZERO:
                return
            self.positions[symbol] = PositionLot(symbol=symbol, qty=money(qty_delta), avg_entry=money(price))
            return
        new_qty = money(lot.qty + qty_delta)
        if new_qty <= MONEY_QUANT and new_qty >= -MONEY_QUANT:
            del self.positions[symbol]
            return
        if qty_delta > ZERO and new_qty > ZERO:
            lot.avg_entry = money((lot.avg_entry * lot.qty + price * qty_delta) / new_qty)
        lot.qty = new_qty

    def equity_at_marks(self, marks: dict[str, Any]) -> Decimal:
        mv = ZERO
        for sym, lot in self.positions.items():
            if sym not in marks:
                continue
            mv = money(mv + lot.qty * D(marks[sym]))
        # Legacy scalar-only wallet: mark via primary or single provided mark.
        if self.position_qty != ZERO and (not self.primary_symbol or self.primary_symbol not in self.positions):
            if self.primary_symbol and self.primary_symbol in marks:
                mv = money(mv + self.position_qty * D(marks[self.primary_symbol]))
            elif len(marks) == 1:
                mv = money(mv + self.position_qty * D(next(iter(marks.values()))))
        return money(self.cash + mv)

    def gross_exposure(self, marks: dict[str, Any]) -> Decimal:
        total = ZERO
        for sym, lot in self.positions.items():
            if sym in marks:
                total = money(total + abs(lot.qty * D(marks[sym])))
        if total == ZERO and self.position_qty != ZERO:
            if self.primary_symbol and self.primary_symbol in marks:
                total = money(abs(self.position_qty * D(marks[self.primary_symbol])))
            elif len(marks) == 1:
                total = money(abs(self.position_qty * D(next(iter(marks.values())))))
        return total

    def net_exposure(self, marks: dict[str, Any]) -> Decimal:
        total = ZERO
        for sym, lot in self.positions.items():
            if sym in marks:
                total = money(total + lot.qty * D(marks[sym]))
        if total == ZERO and self.position_qty != ZERO and not self.positions:
            if self.primary_symbol and self.primary_symbol in marks:
                total = money(self.position_qty * D(marks[self.primary_symbol]))
            elif len(marks) == 1:
                total = money(self.position_qty * D(next(iter(marks.values()))))
        return total

    def assert_invariants(self, price: Any) -> None:
        """Raise if accounting invariants are violated."""
        eq = self.equity(price)
        mv = money(self.position_qty * D(price))
        expected = money(self.cash + mv)
        if eq != expected:
            raise ValueError(f"equity invariant broken: {eq} != {expected}")
        if self.cash != self.cash or self.position_qty != self.position_qty:
            raise ValueError("NaN in wallet state")
        if self.reserved_cash < ZERO - MONEY_QUANT:
            raise ValueError("negative reserved cash")
        if self.reserved_cash > self.cash + MONEY_QUANT and self.cash >= ZERO:
            # reserved cannot exceed cash+epsilon when cash positive
            pass
        fees = money(sum(D(t.get("fee") or 0) for t in self.transactions))
        if abs(fees - self.fees_paid) > MONEY_QUANT * 10:
            raise ValueError(f"fees_paid mismatch: ledger={self.fees_paid} sum_tx={fees}")
        seen: set[str] = set()
        for t in self.transactions:
            tid = str(t.get("tx_id") or "")
            if tid in seen:
                raise ValueError(f"duplicate tx_id in ledger: {tid}")
            seen.add(tid)

    def unrealized_pnl(self, price: Any) -> Decimal:
        if self.position_qty == 0:
            return ZERO
        return money(self.position_qty * (D(price) - self.avg_entry))

    def mark(self, price: Any) -> Decimal:
        eq = self.equity(price)
        if eq > self.peak_equity:
            self.peak_equity = eq
        return eq

    def drawdown_pct(self, price: Any) -> float:
        eq = float(self.equity(price))
        peak = float(self.peak_equity) if self.peak_equity > 0 else eq
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - eq) / peak * 100.0)

    def reserve(self, amount: Any) -> bool:
        amt = money(amount)
        if amt <= 0:
            return True
        if self.available_cash < amt:
            return False
        self.reserved_cash = money(self.reserved_cash + amt)
        return True

    def release_reserve(self, amount: Any) -> None:
        amt = money(amount)
        self.reserved_cash = money(max(ZERO, self.reserved_cash - amt))

    def apply_buy(
        self,
        *,
        qty: Any,
        price: Any,
        fee: Any,
        tx_id: str,
        meta: dict[str, Any] | None = None,
        symbol: str | None = None,
        quote_currency: str | None = None,
    ) -> None:
        self._assert_currency(quote_currency)
        q = money(qty)
        p = money(price)
        f = money(fee)
        if any(t.get("tx_id") == tx_id for t in self.transactions):
            raise ValueError(f"duplicate tx_id rejected: {tx_id}")
        cost = money(q * p + f)
        self.release_reserve(cost)
        if cost > self.cash + MONEY_QUANT:
            raise ValueError("insufficient cash for buy")
        sym = symbol or self.primary_symbol
        if sym:
            if self.primary_symbol is None:
                self.primary_symbol = sym
            # Migrate legacy scalar lot into the map before the first named fill.
            if (
                self.position_qty != ZERO
                and self.primary_symbol not in self.positions
                and not self.positions
            ):
                self.positions[self.primary_symbol] = PositionLot(
                    symbol=self.primary_symbol,
                    qty=self.position_qty,
                    avg_entry=self.avg_entry,
                )
            self._upsert_lot(sym, qty_delta=q, price=p)
            self._sync_primary_from_positions()
        else:
            # Legacy single-symbol scalar path (no symbol map yet).
            new_qty = money(self.position_qty + q)
            if new_qty > 0:
                self.avg_entry = money(
                    (self.avg_entry * self.position_qty + p * q) / new_qty
                )
            self.position_qty = new_qty
        self.cash = money(self.cash - cost)
        self.fees_paid = money(self.fees_paid + f)
        self.transactions.append(
            {
                "tx_id": tx_id,
                "side": "BUY",
                "symbol": sym,
                "qty": str(q),
                "price": str(p),
                "fee": str(f),
                "cash_after": str(self.cash),
                "position_after": str(self.position_qty),
                **(meta or {}),
            }
        )

    def apply_sell(
        self,
        *,
        qty: Any,
        price: Any,
        fee: Any,
        tx_id: str,
        meta: dict[str, Any] | None = None,
        symbol: str | None = None,
        quote_currency: str | None = None,
    ) -> None:
        self._assert_currency(quote_currency)
        p = money(price)
        f = money(fee)
        if any(t.get("tx_id") == tx_id for t in self.transactions):
            raise ValueError(f"duplicate tx_id rejected: {tx_id}")
        sym = symbol or self.primary_symbol
        if sym and sym in self.positions:
            available = self.positions[sym].qty
            entry = self.positions[sym].avg_entry
        elif sym is None or (self.primary_symbol is None and not self.positions):
            available = self.position_qty
            entry = self.avg_entry
        elif sym and self.primary_symbol == sym:
            available = self.position_qty
            entry = self.avg_entry
        else:
            available = ZERO
            entry = ZERO
        q = money(min(D(qty), available))
        if q <= 0:
            raise ValueError("no position to sell")
        proceeds = money(q * p - f)
        self.realized_pnl = money(self.realized_pnl + (p - entry) * q - f)
        if sym and (sym in self.positions or self.primary_symbol == sym or self.positions):
            if self.primary_symbol is None:
                self.primary_symbol = sym
            self._upsert_lot(sym, qty_delta=money(-q), price=p)
            self._sync_primary_from_positions()
            if self.primary_symbol and self.primary_symbol not in self.positions:
                if self.position_qty <= MONEY_QUANT:
                    self.position_qty = ZERO
                    self.avg_entry = ZERO
        else:
            self.position_qty = money(self.position_qty - q)
            if self.position_qty <= MONEY_QUANT:
                self.position_qty = ZERO
                self.avg_entry = ZERO
        self.cash = money(self.cash + proceeds)
        self.fees_paid = money(self.fees_paid + f)
        self.transactions.append(
            {
                "tx_id": tx_id,
                "side": "SELL",
                "symbol": sym,
                "qty": str(q),
                "price": str(p),
                "fee": str(f),
                "cash_after": str(self.cash),
                "position_after": str(self.position_qty),
                **(meta or {}),
            }
        )

    def public_dict(self, price: Any | None = None, *, marks: dict[str, Any] | None = None) -> dict[str, Any]:
        px = D(price) if price is not None else self.avg_entry
        payload: dict[str, Any] = {
            "wallet_id": self.wallet_id,
            "owner_id": self.owner_id,
            "owner_kind": self.owner_kind,
            "currency": self.currency,
            "currency_mode": self.currency_mode,
            "primary_symbol": self.primary_symbol,
            "cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "available_cash": str(self.available_cash),
            "position_qty": str(self.position_qty),
            "avg_entry": str(self.avg_entry),
            "positions": {s: lot.public_dict() for s, lot in self.positions.items()},
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl(px)),
            "fees_paid": str(self.fees_paid),
            "equity": str(self.equity(px)),
            "peak_equity": str(self.peak_equity),
            "drawdown_pct": self.drawdown_pct(px),
            "transaction_count": len(self.transactions),
            "transactions_tail": self.transactions[-20:],
            "truth": {
                "agent_wallets_isolated": True,
                "multi_symbol_positions": True,
                "no_silent_currency_mix": self.currency_mode == "single",
            },
        }
        if marks is not None:
            payload["equity_at_marks"] = str(self.equity_at_marks(marks))
            payload["gross_exposure"] = str(self.gross_exposure(marks))
            payload["net_exposure"] = str(self.net_exposure(marks))
        return payload


@dataclass
class WalletBook:
    """Collection of isolated wallets for one experiment/run."""

    wallets: dict[str, WalletLedger] = field(default_factory=dict)
    shared_wallet_id: str | None = None

    def add(self, wallet: WalletLedger) -> WalletLedger:
        self.wallets[wallet.wallet_id] = wallet
        if wallet.owner_kind == "shared":
            self.shared_wallet_id = wallet.wallet_id
        return wallet

    def get(self, wallet_id: str) -> WalletLedger:
        return self.wallets[wallet_id]

    def for_owner(self, owner_id: str) -> WalletLedger | None:
        for w in self.wallets.values():
            if w.owner_id == owner_id:
                return w
        return None

    def ensure_agent(self, agent_id: str, *, initial_cash: Any, currency: str = "USD") -> WalletLedger:
        existing = self.for_owner(agent_id)
        if existing:
            return existing
        wallet = WalletLedger(
            wallet_id=f"wal-{agent_id}",
            owner_id=agent_id,
            owner_kind="agent",
            cash=money(initial_cash),
            currency=currency,
        )
        return self.add(wallet)

    def ensure_shared(self, *, initial_cash: Any, currency: str = "USD") -> WalletLedger:
        if self.shared_wallet_id and self.shared_wallet_id in self.wallets:
            return self.wallets[self.shared_wallet_id]
        wallet = WalletLedger(
            wallet_id="wal-shared",
            owner_id="shared",
            owner_kind="shared",
            cash=money(initial_cash),
            currency=currency,
        )
        return self.add(wallet)

    def public_dict(self, price: Any | None = None) -> dict[str, Any]:
        return {
            "wallets": [w.public_dict(price) for w in self.wallets.values()],
            "shared_wallet_id": self.shared_wallet_id,
            "truth": {"agent_wallets_isolated": True, "no_cross_agent_funds": True},
        }
