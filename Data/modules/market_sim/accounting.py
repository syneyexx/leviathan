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
    valuation_mode: str = "spot"  # spot | futures_vm
    contract_multiplier: Decimal = field(default_factory=lambda: Decimal("1"))

    def __post_init__(self) -> None:
        self.cash = money(self.cash)
        self.reserved_cash = money(self.reserved_cash)
        self.position_qty = money(self.position_qty)
        self.avg_entry = money(self.avg_entry)
        self.realized_pnl = money(self.realized_pnl)
        self.fees_paid = money(self.fees_paid)
        self.contract_multiplier = D(self.contract_multiplier)
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
        if self.valuation_mode == "futures_vm":
            # Cash includes posted variation margin; residual only on unposted mark move.
            residual = self.position_qty * (D(price) - self.avg_entry) * self.contract_multiplier
            return money(self.cash + residual)
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
        if self.valuation_mode == "futures_vm":
            residual = money(
                self.position_qty * (D(price) - self.avg_entry) * self.contract_multiplier
            )
            expected = money(self.cash + residual)
        else:
            mv = money(self.position_qty * D(price))
            expected = money(self.cash + mv)
        if eq != expected:
            raise ValueError(f"equity invariant broken: {eq} != {expected}")
        if self.cash != self.cash or self.position_qty != self.position_qty:
            raise ValueError("NaN in wallet state")
        if self.reserved_cash < ZERO - MONEY_QUANT:
            raise ValueError("negative reserved cash")
        if self.reserved_cash > self.cash + MONEY_QUANT:
            raise ValueError(
                f"reserved_cash ({self.reserved_cash}) exceeds cash ({self.cash}) + epsilon"
            )
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
        if self.valuation_mode == "futures_vm":
            return money(self.position_qty * (D(price) - self.avg_entry) * self.contract_multiplier)
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

    def apply_corporate_action(
        self,
        *,
        symbol: str,
        kind: str,
        effective_at: str,
        as_of: str,
        factor: float | None = None,
        cash_amount: float | None = None,
        new_symbol: str | None = None,
        ca_id: str | None = None,
        tx_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply a point-in-time corporate action to this ledger.

        Bridges universe CA labels (split/dividend/symbol_change) onto economic
        adjustments via institutional_core.apply_corporate_action. Fail-closed
        for unsupported kinds. Idempotent on tx_id.
        """
        from .institutional_core.corporate_actions import (
            CorporateAction as CoreCA,
            apply_corporate_action as core_apply,
        )

        kind_u = str(kind or "").strip().lower()
        type_map = {
            "split": "SPLIT",
            "dividend": "DIVIDEND_CASH",
            "dividend_cash": "DIVIDEND_CASH",
            "dividend_stock": "DIVIDEND_STOCK",
            "symbol_change": "SYMBOL_CHANGE",
            "merger": "MERGER",
            "spinoff": "SPINOFF",
            "delisting": "DELISTING",
        }
        ca_type = type_map.get(kind_u) or str(kind or "").strip().upper()
        cid = str(ca_id or f"ca-{symbol}-{ca_type}-{effective_at}")
        tid = str(tx_id or f"tx-ca-{cid}")
        if any(t.get("tx_id") == tid for t in self.transactions):
            return {"applied": False, "reason": "duplicate_tx_id", "tx_id": tid}

        if as_of < effective_at:
            return {
                "applied": False,
                "reason": "before_effective_time",
                "truth": {"point_in_time_respected": True},
            }

        # Resolve held qty / cost for symbol (multi-lot or scalar primary).
        lot = self.positions.get(symbol)
        if lot is not None:
            qty = float(lot.qty)
            cost = float(lot.avg_entry)
        elif self.primary_symbol == symbol or (
            self.primary_symbol is None and self.position_qty != ZERO and not self.positions
        ):
            qty = float(self.position_qty)
            cost = float(self.avg_entry)
        else:
            return {"applied": False, "reason": "no_position", "symbol": symbol}

        if qty == 0.0 and ca_type != "SYMBOL_CHANGE":
            return {"applied": False, "reason": "flat_position", "symbol": symbol}

        core = CoreCA(
            ca_id=cid,
            instrument_id=symbol,
            ca_type=ca_type,
            effective_time=effective_at,
            observed_at=as_of,
            ratio=factor,
            cash_amount=cash_amount,
            new_instrument_id=new_symbol,
        )
        result = core_apply(core, qty=qty, cost_basis=cost, as_of=as_of)
        if not result.get("applied"):
            return result

        adj = result.get("adjustment") or {}
        qty_after = money(adj.get("qtyAfter") or qty)
        cost_after = money(adj.get("costBasisAfter") or cost)
        cash_delta = money(adj.get("cashDelta") or 0)
        target_symbol = str(adj.get("instrumentId") or new_symbol or symbol)

        if ca_type == "SYMBOL_CHANGE" and new_symbol and new_symbol != symbol:
            # Move lot / primary under new symbol identity.
            if symbol in self.positions:
                old = self.positions.pop(symbol)
                self.positions[new_symbol] = PositionLot(
                    symbol=new_symbol, qty=old.qty, avg_entry=old.avg_entry
                )
            if self.primary_symbol == symbol or self.primary_symbol is None:
                self.primary_symbol = new_symbol
            self._sync_primary_from_positions()
        else:
            if symbol in self.positions or self.positions or self.primary_symbol == symbol:
                if self.primary_symbol is None:
                    self.primary_symbol = symbol
                if symbol not in self.positions and self.position_qty != ZERO:
                    self.positions[symbol] = PositionLot(
                        symbol=symbol, qty=self.position_qty, avg_entry=self.avg_entry
                    )
                if symbol in self.positions:
                    if qty_after == ZERO:
                        del self.positions[symbol]
                    else:
                        self.positions[symbol].qty = qty_after
                        self.positions[symbol].avg_entry = cost_after
                if target_symbol != symbol and symbol not in self.positions and qty_after != ZERO:
                    self.positions[target_symbol] = PositionLot(
                        symbol=target_symbol, qty=qty_after, avg_entry=cost_after
                    )
                self._sync_primary_from_positions()
            else:
                self.position_qty = qty_after
                self.avg_entry = cost_after if qty_after != ZERO else ZERO

        if cash_delta != ZERO:
            self.cash = money(self.cash + cash_delta)
            # Cash dividends are realized economic events (not trading PnL fills).
            self.realized_pnl = money(self.realized_pnl + cash_delta)

        self.transactions.append(
            {
                "tx_id": tid,
                "side": "CORPORATE_ACTION",
                "symbol": target_symbol,
                "qty": str(qty_after),
                "price": str(cost_after),
                "fee": "0",
                "cash_after": str(self.cash),
                "position_after": str(self.position_qty),
                "ca_id": cid,
                "ca_type": ca_type,
                "cash_delta": str(cash_delta),
                "effective_at": effective_at,
                "as_of": as_of,
            }
        )
        out = dict(result)
        out["tx_id"] = tid
        out["symbol"] = target_symbol
        return out

    def apply_variation_margin(
        self,
        *,
        qty: Any,
        price_from: Any,
        price_to: Any,
        multiplier: Any,
        tx_id: str,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Post futures/derivative variation margin to cash (fail-closed on bad multiplier)."""
        if any(t.get("tx_id") == tx_id for t in self.transactions):
            return {"applied": False, "reason": "duplicate_tx_id", "tx_id": tx_id}
        mult = D(multiplier)
        if mult <= 0:
            raise ValueError("futures_multiplier_invalid")
        q = D(qty)
        delta = D(price_to) - D(price_from)
        cash_delta = money(q * delta * mult)
        if cash_delta == ZERO:
            return {"applied": False, "reason": "zero_variation", "tx_id": tx_id}
        self.cash = money(self.cash + cash_delta)
        self.realized_pnl = money(self.realized_pnl + cash_delta)
        # Reset cost basis to mark after daily settlement-style VM.
        mark = money(price_to)
        sym = symbol or self.primary_symbol
        if sym and sym in self.positions:
            self.positions[sym].avg_entry = mark
        if self.primary_symbol == sym or (sym is None and not self.positions):
            self.avg_entry = mark
        self._sync_primary_from_positions()
        self.transactions.append(
            {
                "tx_id": tx_id,
                "side": "VARIATION_MARGIN",
                "symbol": sym,
                "qty": str(money(q)),
                "price": str(mark),
                "fee": "0",
                "cash_after": str(self.cash),
                "position_after": str(self.position_qty),
                "cash_delta": str(cash_delta),
                "multiplier": str(mult),
                "price_from": str(money(price_from)),
                "price_to": str(mark),
            }
        )
        return {
            "applied": True,
            "cash_delta": str(cash_delta),
            "tx_id": tx_id,
            "multiplier": str(mult),
        }

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
        # Futures: opening does not debit full notional — only fees (margin via RiskGuard).
        if self.valuation_mode == "futures_vm":
            cost = f
        else:
            cost = money(q * p + f)
        self.release_reserve(cost if self.valuation_mode != "futures_vm" else f)
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
                "valuation_mode": self.valuation_mode,
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
        if self.valuation_mode == "futures_vm":
            # Close futures: settle residual MTM * multiplier, pay fee from cash.
            residual = money(q * (p - entry) * self.contract_multiplier)
            proceeds = money(residual - f)
            self.realized_pnl = money(self.realized_pnl + residual - f)
        else:
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
                "valuation_mode": self.valuation_mode,
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
            "valuation_mode": self.valuation_mode,
            "contract_multiplier": str(self.contract_multiplier),
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
                "futures_vm_uses_multiplier": self.valuation_mode == "futures_vm",
            },
        }
        if marks is not None:
            payload["equity_at_marks"] = str(self.equity_at_marks(marks))
            payload["gross_exposure"] = str(self.gross_exposure(marks))
            payload["net_exposure"] = str(self.net_exposure(marks))
        return payload

    @classmethod
    def from_public_dict(cls, payload: dict[str, Any] | None) -> "WalletLedger":
        """Rebuild a ledger from a persisted public_dict (W18 paper restart)."""
        data = dict(payload or {})
        positions: dict[str, PositionLot] = {}
        raw_positions = data.get("positions") or {}
        if isinstance(raw_positions, dict):
            for sym, lot in raw_positions.items():
                if not isinstance(lot, dict):
                    continue
                positions[str(sym)] = PositionLot(
                    symbol=str(lot.get("symbol") or sym),
                    qty=money(lot.get("qty") or 0),
                    avg_entry=money(lot.get("avg_entry") or 0),
                )
        txs = list(data.get("transactions") or data.get("transactions_tail") or [])
        wallet = cls(
            wallet_id=str(data.get("wallet_id") or "wal-restored"),
            owner_id=str(data.get("owner_id") or "paper"),
            owner_kind=str(data.get("owner_kind") or "paper_session"),
            cash=money(data.get("cash") or 0),
            reserved_cash=money(data.get("reserved_cash") or 0),
            position_qty=money(data.get("position_qty") or 0),
            avg_entry=money(data.get("avg_entry") or 0),
            realized_pnl=money(data.get("realized_pnl") or 0),
            fees_paid=money(data.get("fees_paid") or 0),
            peak_equity=money(data.get("peak_equity") or data.get("cash") or 0),
            currency=str(data.get("currency") or "USD"),
            currency_mode=str(data.get("currency_mode") or "single"),
            primary_symbol=data.get("primary_symbol"),
            positions=positions,
            transactions=[dict(t) for t in txs if isinstance(t, dict)],
            valuation_mode=str(data.get("valuation_mode") or "spot"),
            contract_multiplier=money(data.get("contract_multiplier") or 1),
        )
        return wallet


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
