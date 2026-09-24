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
class WalletLedger:
    """One agent's (or shared) virtual wallet — never mixed with another agent's."""

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

    @property
    def available_cash(self) -> Decimal:
        return money(self.cash - self.reserved_cash)

    def equity(self, price: Any) -> Decimal:
        return money(self.cash + self.position_qty * D(price))

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

    def apply_buy(self, *, qty: Any, price: Any, fee: Any, tx_id: str, meta: dict[str, Any] | None = None) -> None:
        q = money(qty)
        p = money(price)
        f = money(fee)
        cost = money(q * p + f)
        self.release_reserve(cost)
        if cost > self.cash + MONEY_QUANT:
            raise ValueError("insufficient cash for buy")
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
                "qty": str(q),
                "price": str(p),
                "fee": str(f),
                "cash_after": str(self.cash),
                "position_after": str(self.position_qty),
                **(meta or {}),
            }
        )

    def apply_sell(self, *, qty: Any, price: Any, fee: Any, tx_id: str, meta: dict[str, Any] | None = None) -> None:
        q = money(min(D(qty), self.position_qty))
        p = money(price)
        f = money(fee)
        if q <= 0:
            raise ValueError("no position to sell")
        proceeds = money(q * p - f)
        self.realized_pnl = money(self.realized_pnl + (p - self.avg_entry) * q - f)
        self.position_qty = money(self.position_qty - q)
        self.cash = money(self.cash + proceeds)
        self.fees_paid = money(self.fees_paid + f)
        if self.position_qty <= MONEY_QUANT:
            self.position_qty = ZERO
            self.avg_entry = ZERO
        self.transactions.append(
            {
                "tx_id": tx_id,
                "side": "SELL",
                "qty": str(q),
                "price": str(p),
                "fee": str(f),
                "cash_after": str(self.cash),
                "position_after": str(self.position_qty),
                **(meta or {}),
            }
        )

    def public_dict(self, price: Any | None = None) -> dict[str, Any]:
        px = D(price) if price is not None else self.avg_entry
        return {
            "wallet_id": self.wallet_id,
            "owner_id": self.owner_id,
            "owner_kind": self.owner_kind,
            "currency": self.currency,
            "cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "available_cash": str(self.available_cash),
            "position_qty": str(self.position_qty),
            "avg_entry": str(self.avg_entry),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl(px)),
            "fees_paid": str(self.fees_paid),
            "equity": str(self.equity(px)),
            "peak_equity": str(self.peak_equity),
            "drawdown_pct": self.drawdown_pct(px),
            "transaction_count": len(self.transactions),
            "transactions_tail": self.transactions[-20:],
        }


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
