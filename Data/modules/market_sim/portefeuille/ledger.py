"""Multi-asset PortfolioBook — Decimal paper accounting with long/short netting.

Netting rules (deterministic):
  BUY  on flat/long  → increase long (avg entry weighted)
  BUY  on short      → COVER (reduce short); leftover opens long
  SELL on long       → reduce long; if shorting enabled and qty > long → open short
  SELL on flat/short without shorting → reject
  SHORT              → open/increase short (requires shorting_enabled)
  COVER              → reduce short only

Reservations are concurrency-safe when callers hold the portfolio write lock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..accounting import D, MONEY_QUANT, ZERO, money
from .assets import asset_registry


@dataclass
class PositionState:
    symbol: str
    side: str  # LONG | SHORT
    qty: Decimal = ZERO
    avg_entry: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    margin_used: Decimal = ZERO
    short_proceeds: Decimal = ZERO
    agent_id: str | None = None
    orchestra_id: str | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    opened_at: str = ""
    updated_at: str = ""
    position_id: str = ""

    def __post_init__(self) -> None:
        self.qty = money(self.qty)
        self.avg_entry = money(self.avg_entry)
        self.realized_pnl = money(self.realized_pnl)
        self.fees = money(self.fees)
        self.margin_used = money(self.margin_used)
        self.short_proceeds = money(self.short_proceeds)
        if not self.position_id:
            self.position_id = str(uuid.uuid4())


@dataclass
class PortfolioBook:
    """Authoritative multi-asset paper capital book for one Portefeuille."""

    portfolio_id: str
    cash: Decimal
    reserved_cash: Decimal = ZERO
    currency: str = "USD"
    shorting_enabled: bool = False
    initial_margin_pct: Decimal = Decimal("50")
    maintenance_margin_pct: Decimal = Decimal("30")
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO
    peak_equity: Decimal = ZERO
    positions: dict[str, PositionState] = field(default_factory=dict)
    reservations: dict[str, Decimal] = field(default_factory=dict)  # reservation_id -> amount
    closed_trades_won: int = 0
    closed_trades_lost: int = 0
    closed_trades_flat: int = 0

    def __post_init__(self) -> None:
        self.cash = money(self.cash)
        self.reserved_cash = money(self.reserved_cash)
        self.realized_pnl = money(self.realized_pnl)
        self.fees_paid = money(self.fees_paid)
        if self.peak_equity <= 0:
            self.peak_equity = self.cash

    @property
    def available_cash(self) -> Decimal:
        return money(self.cash - self.reserved_cash)

    def market_value(self, marks: dict[str, Any]) -> Decimal:
        """Signed net market value of open positions (long +, short −)."""
        total = ZERO
        for sym, pos in self.positions.items():
            if pos.qty <= ZERO:
                continue
            px = D(marks.get(sym, pos.avg_entry))
            if pos.side == "LONG":
                total = money(total + pos.qty * px)
            else:
                total = money(total - pos.qty * px)
        return total

    def equity(self, marks: dict[str, Any]) -> Decimal:
        """Equity = cash + long MV − short liability (proceeds already in cash)."""
        eq = self.cash
        for sym, pos in self.positions.items():
            if pos.qty <= ZERO:
                continue
            px = D(marks.get(sym, pos.avg_entry))
            if pos.side == "LONG":
                eq = money(eq + pos.qty * px)
            else:
                eq = money(eq - pos.qty * px)
        return money(eq)

    def unrealized_pnl(self, marks: dict[str, Any]) -> Decimal:
        total = ZERO
        for sym, pos in self.positions.items():
            if pos.qty <= ZERO:
                continue
            px = D(marks.get(sym, pos.avg_entry))
            if pos.side == "LONG":
                total = money(total + pos.qty * (px - pos.avg_entry))
            else:
                total = money(total + pos.qty * (pos.avg_entry - px))
        return total

    def gross_exposure(self, marks: dict[str, Any]) -> Decimal:
        total = ZERO
        for sym, pos in self.positions.items():
            if pos.qty <= ZERO:
                continue
            px = D(marks.get(sym, pos.avg_entry))
            total = money(total + abs(pos.qty * px))
        return total

    def net_exposure(self, marks: dict[str, Any]) -> Decimal:
        total = ZERO
        for sym, pos in self.positions.items():
            if pos.qty <= ZERO:
                continue
            px = D(marks.get(sym, pos.avg_entry))
            signed = pos.qty * px if pos.side == "LONG" else -pos.qty * px
            total = money(total + signed)
        return total

    def margin_used(self, marks: dict[str, Any]) -> Decimal:
        total = ZERO
        for sym, pos in self.positions.items():
            if pos.side == "SHORT" and pos.qty > ZERO:
                px = D(marks.get(sym, pos.avg_entry))
                total = money(total + pos.qty * px * self.initial_margin_pct / Decimal("100"))
        return total

    def mark(self, marks: dict[str, Any]) -> Decimal:
        eq = self.equity(marks)
        if eq > self.peak_equity:
            self.peak_equity = eq
        return eq

    def drawdown_pct(self, marks: dict[str, Any]) -> float:
        eq = float(self.equity(marks))
        peak = float(self.peak_equity) if self.peak_equity > 0 else eq
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - eq) / peak * 100.0)

    def win_rate(self) -> float | None:
        decided = self.closed_trades_won + self.closed_trades_lost
        if decided <= 0:
            return None
        return self.closed_trades_won / decided * 100.0

    # --- Reservations ---

    def reserve(self, amount: Any, *, reservation_id: str | None = None) -> str | None:
        amt = money(amount)
        if amt <= ZERO:
            return reservation_id or str(uuid.uuid4())
        if self.available_cash < amt:
            return None
        rid = reservation_id or str(uuid.uuid4())
        self.reserved_cash = money(self.reserved_cash + amt)
        self.reservations[rid] = money(self.reservations.get(rid, ZERO) + amt)
        return rid

    def release_reserve(self, reservation_id: str | None = None, amount: Any | None = None) -> None:
        if reservation_id and reservation_id in self.reservations:
            amt = self.reservations.pop(reservation_id)
            self.reserved_cash = money(max(ZERO, self.reserved_cash - amt))
            return
        if amount is not None:
            amt = money(amount)
            self.reserved_cash = money(max(ZERO, self.reserved_cash - amt))

    def assert_invariants(self, marks: dict[str, Any] | None = None) -> None:
        marks = marks or {}
        if self.reserved_cash < ZERO - MONEY_QUANT:
            raise ValueError("negative reserved cash")
        if self.reserved_cash > self.cash + MONEY_QUANT and self.cash >= ZERO:
            # Allow temporary edge on mark; hard fail on large overshoot
            if self.reserved_cash > self.cash + money(1):
                raise ValueError("reserved cash exceeds cash")
        for pos in self.positions.values():
            if pos.qty < ZERO:
                raise ValueError(f"negative qty on {pos.symbol}")
            if pos.side not in ("LONG", "SHORT"):
                raise ValueError(f"invalid side {pos.side}")
        # Equity identity: cash + long MV - short liability
        _ = self.equity(marks)

    # --- Fills ---

    def apply_fill(
        self,
        *,
        symbol: str,
        side: str,
        qty: Any,
        price: Any,
        fee: Any,
        tx_id: str,
        timestamp: str = "",
        agent_id: str | None = None,
        orchestra_id: str | None = None,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        reservation_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply a paper fill. Returns transaction effect dict."""
        action = side.upper()
        q = money(qty)
        p = money(price)
        f = money(fee)
        if q <= ZERO:
            raise ValueError("qty must be positive")
        if p <= ZERO:
            raise ValueError("price must be positive")

        if reservation_id:
            self.release_reserve(reservation_id)

        pos = self.positions.get(symbol.upper())
        result = "UNKNOWN"
        net_cash = ZERO

        if action == "BUY":
            result, net_cash = self._apply_buy(
                symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
            )
        elif action == "SELL":
            result, net_cash = self._apply_sell(
                symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
            )
        elif action == "SHORT":
            result, net_cash = self._apply_short(
                symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
            )
        elif action == "COVER":
            result, net_cash = self._apply_cover(
                symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
            )
        else:
            raise ValueError(f"unknown side {action}")

        self.fees_paid = money(self.fees_paid + f)
        return {
            "tx_id": tx_id,
            "symbol": symbol.upper(),
            "side": action,
            "qty": str(q),
            "price": str(p),
            "fee": str(f),
            "net_cash_effect": str(net_cash),
            "result": result,
            "cash_after": str(self.cash),
            "position_after": self._pos_public(symbol.upper()),
            **(meta or {}),
        }

    def _pos_public(self, symbol: str) -> dict[str, Any] | None:
        pos = self.positions.get(symbol)
        if not pos or pos.qty <= ZERO:
            return None
        return {
            "symbol": pos.symbol,
            "side": pos.side,
            "qty": str(pos.qty),
            "avg_entry": str(pos.avg_entry),
        }

    def _touch_pos(
        self,
        symbol: str,
        *,
        side: str,
        timestamp: str,
        agent_id: str | None,
        orchestra_id: str | None,
        strategy_id: str | None,
        strategy_version: int | None,
    ) -> PositionState:
        key = symbol.upper()
        pos = self.positions.get(key)
        if pos is None or pos.qty <= ZERO:
            pos = PositionState(
                symbol=key,
                side=side,
                opened_at=timestamp,
                updated_at=timestamp,
                agent_id=agent_id,
                orchestra_id=orchestra_id,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
            )
            self.positions[key] = pos
        else:
            pos.updated_at = timestamp
            # Attribution sticky to opener; do not reattribute
        return pos

    def _apply_buy(
        self, symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
    ) -> tuple[str, Decimal]:
        key = symbol.upper()
        pos = self.positions.get(key)
        cost = money(q * p + f)
        if cost > self.cash + MONEY_QUANT:
            raise ValueError("insufficient cash for buy")

        if pos and pos.side == "SHORT" and pos.qty > ZERO:
            # Cover first
            cover_q = money(min(q, pos.qty))
            leftover = money(q - cover_q)
            cover_cost = money(cover_q * p + f * cover_q / q if q else f)
            # Realize short PnL: entry - cover price
            pnl = money(cover_q * (pos.avg_entry - p) - cover_cost + cover_q * p)
            # Simpler: realized = (avg_entry - p) * cover_q - fee_portion
            fee_portion = money(f * cover_q / q) if q else f
            pnl = money(cover_q * (pos.avg_entry - p) - fee_portion)
            self.realized_pnl = money(self.realized_pnl + pnl)
            pos.realized_pnl = money(pos.realized_pnl + pnl)
            pos.fees = money(pos.fees + fee_portion)
            self.cash = money(self.cash - cover_q * p - fee_portion)
            # Release margin + short proceeds accounting
            margin_release = money(pos.margin_used * cover_q / pos.qty) if pos.qty else ZERO
            pos.margin_used = money(max(ZERO, pos.margin_used - margin_release))
            pos.short_proceeds = money(max(ZERO, pos.short_proceeds - cover_q * pos.avg_entry))
            pos.qty = money(pos.qty - cover_q)
            self._record_closed_trade(pnl)
            result = "COVERED"
            if pos.qty <= MONEY_QUANT:
                del self.positions[key]
            if leftover > ZERO:
                # Open long with leftover
                fee2 = money(f - fee_portion)
                self.cash = money(self.cash - leftover * p - fee2)
                new_pos = self._touch_pos(
                    key,
                    side="LONG",
                    timestamp=timestamp,
                    agent_id=agent_id,
                    orchestra_id=orchestra_id,
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                )
                new_pos.side = "LONG"
                new_pos.qty = leftover
                new_pos.avg_entry = p
                new_pos.fees = money(new_pos.fees + fee2)
                result = "COVERED_AND_OPENED"
            return result, money(-(q * p + f))

        # Long buy / add
        self.cash = money(self.cash - cost)
        pos = self._touch_pos(
            key,
            side="LONG",
            timestamp=timestamp,
            agent_id=agent_id,
            orchestra_id=orchestra_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        if pos.side == "SHORT":
            raise ValueError("internal: unexpected short on buy path")
        new_qty = money(pos.qty + q)
        if new_qty > ZERO:
            pos.avg_entry = money((pos.avg_entry * pos.qty + p * q) / new_qty) if pos.qty > ZERO else p
        pos.qty = new_qty
        pos.side = "LONG"
        pos.fees = money(pos.fees + f)
        return ("INCREASED" if pos.qty > q else "OPENED"), money(-cost)

    def _apply_sell(
        self, symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
    ) -> tuple[str, Decimal]:
        key = symbol.upper()
        pos = self.positions.get(key)
        long_qty = pos.qty if pos and pos.side == "LONG" else ZERO

        if long_qty <= ZERO and not self.shorting_enabled:
            raise ValueError("no long position to sell; shorting disabled")

        sell_from_long = money(min(q, long_qty)) if long_qty > ZERO else ZERO
        short_open = money(q - sell_from_long)
        net_cash = ZERO
        result = "REDUCED"

        if sell_from_long > ZERO:
            assert pos is not None
            fee_portion = money(f * sell_from_long / q) if q else f
            proceeds = money(sell_from_long * p - fee_portion)
            pnl = money(sell_from_long * (p - pos.avg_entry) - fee_portion)
            self.realized_pnl = money(self.realized_pnl + pnl)
            pos.realized_pnl = money(pos.realized_pnl + pnl)
            pos.fees = money(pos.fees + fee_portion)
            self.cash = money(self.cash + proceeds)
            pos.qty = money(pos.qty - sell_from_long)
            net_cash = money(net_cash + proceeds)
            self._record_closed_trade(pnl)
            if pos.qty <= MONEY_QUANT:
                del self.positions[key]
                result = "CLOSED"
            else:
                result = "REDUCED"

        if short_open > ZERO:
            if not self.shorting_enabled:
                raise ValueError("shorting disabled; cannot sell beyond long")
            fee_portion = money(f * short_open / q) if q else ZERO
            r, cash_fx = self._apply_short(
                symbol,
                short_open,
                p,
                fee_portion,
                timestamp,
                agent_id,
                orchestra_id,
                strategy_id,
                strategy_version,
            )
            net_cash = money(net_cash + cash_fx)
            result = "CLOSED_AND_SHORT" if sell_from_long > ZERO else r

        return result, net_cash

    def _apply_short(
        self, symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
    ) -> tuple[str, Decimal]:
        if not self.shorting_enabled:
            raise ValueError("shorting disabled")
        key = symbol.upper()
        pos = self.positions.get(key)
        if pos and pos.side == "LONG" and pos.qty > ZERO:
            raise ValueError("cannot SHORT while long; use SELL to net")

        proceeds = money(q * p - f)
        margin = money(q * p * self.initial_margin_pct / Decimal("100"))
        # Proceeds reserved; margin also reserved from available
        if self.available_cash + proceeds < margin:
            # After receiving proceeds, need margin reserved
            pass
        self.cash = money(self.cash + proceeds)
        # Reserve margin from cash
        rid = self.reserve(margin)
        if rid is None:
            # rollback cash
            self.cash = money(self.cash - proceeds)
            raise ValueError("insufficient margin for short")

        pos = self._touch_pos(
            key,
            side="SHORT",
            timestamp=timestamp,
            agent_id=agent_id,
            orchestra_id=orchestra_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
        if pos.side == "LONG" and pos.qty > ZERO:
            raise ValueError("internal long/short conflict")
        new_qty = money(pos.qty + q) if pos.side == "SHORT" else q
        if pos.side == "SHORT" and pos.qty > ZERO:
            pos.avg_entry = money((pos.avg_entry * pos.qty + p * q) / new_qty)
        else:
            pos.avg_entry = p
            pos.side = "SHORT"
            pos.qty = ZERO
            new_qty = q
        pos.qty = new_qty
        pos.side = "SHORT"
        pos.fees = money(pos.fees + f)
        pos.margin_used = money(pos.margin_used + margin)
        pos.short_proceeds = money(pos.short_proceeds + q * p)
        # Bind reservation to position metadata via margin (released on cover)
        self.release_reserve(rid)  # convert free reservation into position.margin_used tracking
        # Keep cash but mark margin as reserved_cash
        self.reserved_cash = money(self.reserved_cash + margin)
        return ("INCREASED" if pos.qty > q else "OPENED"), money(proceeds)

    def _apply_cover(
        self, symbol, q, p, f, timestamp, agent_id, orchestra_id, strategy_id, strategy_version
    ) -> tuple[str, Decimal]:
        key = symbol.upper()
        pos = self.positions.get(key)
        if not pos or pos.side != "SHORT" or pos.qty <= ZERO:
            raise ValueError("no short position to cover")
        cover_q = money(min(q, pos.qty))
        fee_portion = money(f * cover_q / q) if q else f
        cost = money(cover_q * p + fee_portion)
        if cost > self.cash + MONEY_QUANT:
            raise ValueError("insufficient cash to cover")
        pnl = money(cover_q * (pos.avg_entry - p) - fee_portion)
        self.realized_pnl = money(self.realized_pnl + pnl)
        pos.realized_pnl = money(pos.realized_pnl + pnl)
        self.cash = money(self.cash - cost)
        margin_release = money(pos.margin_used * cover_q / pos.qty) if pos.qty else ZERO
        pos.margin_used = money(max(ZERO, pos.margin_used - margin_release))
        self.reserved_cash = money(max(ZERO, self.reserved_cash - margin_release))
        pos.short_proceeds = money(max(ZERO, pos.short_proceeds - cover_q * pos.avg_entry))
        pos.qty = money(pos.qty - cover_q)
        pos.fees = money(pos.fees + fee_portion)
        pos.updated_at = timestamp
        self._record_closed_trade(pnl)
        if pos.qty <= MONEY_QUANT:
            del self.positions[key]
            return "CLOSED", money(-cost)
        return "COVERED", money(-cost)

    def _record_closed_trade(self, pnl: Decimal) -> None:
        if pnl > MONEY_QUANT:
            self.closed_trades_won += 1
        elif pnl < -MONEY_QUANT:
            self.closed_trades_lost += 1
        else:
            self.closed_trades_flat += 1

    def open_positions_public(self, marks: dict[str, Any], *, equity: Decimal | None = None) -> list[dict[str, Any]]:
        eq = equity if equity is not None else self.equity(marks)
        out: list[dict[str, Any]] = []
        for sym, pos in sorted(self.positions.items()):
            if pos.qty <= ZERO:
                continue
            px = D(marks.get(sym, pos.avg_entry))
            if pos.side == "LONG":
                mv = money(pos.qty * px)
                upnl = money(pos.qty * (px - pos.avg_entry))
                cost = money(pos.qty * pos.avg_entry)
            else:
                mv = money(-pos.qty * px)
                upnl = money(pos.qty * (pos.avg_entry - px))
                cost = money(pos.qty * pos.avg_entry)
            pnl_pct = float(upnl / cost * 100) if cost > ZERO else 0.0
            alloc = float(abs(mv) / eq * 100) if eq > ZERO else 0.0
            meta = asset_registry.get(sym)
            # Risk heuristic from allocation
            risk = "Low" if alloc < 10 else ("Medium" if alloc < 25 else "High")
            out.append(
                {
                    "position_id": pos.position_id,
                    "portfolio_id": self.portfolio_id,
                    "symbol": sym,
                    "display_name": meta.display_name,
                    "asset_class": meta.asset_class,
                    "side": pos.side,
                    "qty": str(pos.qty),
                    "avg_entry_price": str(pos.avg_entry),
                    "mark_price": str(px),
                    "market_value": str(mv),
                    "cost_basis": str(cost),
                    "realized_pnl": str(pos.realized_pnl),
                    "unrealized_pnl": str(upnl),
                    "pnl_pct": f"{pnl_pct:.2f}",
                    "fees": str(pos.fees),
                    "margin_used": str(pos.margin_used),
                    "allocation_pct": round(alloc, 2),
                    "risk": risk,
                    "agent_id": pos.agent_id,
                    "orchestra_id": pos.orchestra_id,
                    "strategy_id": pos.strategy_id,
                    "strategy_version": pos.strategy_version,
                    "opened_at": pos.opened_at,
                    "updated_at": pos.updated_at,
                    "status": "OPEN",
                }
            )
        return out

    def to_wallet_projection(self, symbol: str, mark: Any) -> Any:
        """Project single-symbol state onto WalletLedger for RiskGuard compatibility."""
        from ..accounting import WalletLedger

        pos = self.positions.get(symbol.upper())
        qty = pos.qty if pos and pos.side == "LONG" else ZERO
        # For shorts, RiskGuard long-only path sees 0 long qty; short checks elsewhere
        avg = pos.avg_entry if pos else ZERO
        return WalletLedger(
            wallet_id=f"pf-{self.portfolio_id}-{symbol}",
            owner_id=self.portfolio_id,
            owner_kind="paper",
            cash=self.cash,
            reserved_cash=self.reserved_cash,
            position_qty=qty,
            avg_entry=avg,
            realized_pnl=self.realized_pnl,
            fees_paid=self.fees_paid,
            peak_equity=self.peak_equity,
            currency=self.currency,
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "currency": self.currency,
            "shorting_enabled": self.shorting_enabled,
            "initial_margin_pct": str(self.initial_margin_pct),
            "maintenance_margin_pct": str(self.maintenance_margin_pct),
            "realized_pnl": str(self.realized_pnl),
            "fees_paid": str(self.fees_paid),
            "peak_equity": str(self.peak_equity),
            "closed_trades_won": self.closed_trades_won,
            "closed_trades_lost": self.closed_trades_lost,
            "closed_trades_flat": self.closed_trades_flat,
            "reservations": {k: str(v) for k, v in self.reservations.items()},
            "positions": {
                sym: {
                    "position_id": p.position_id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "qty": str(p.qty),
                    "avg_entry": str(p.avg_entry),
                    "realized_pnl": str(p.realized_pnl),
                    "fees": str(p.fees),
                    "margin_used": str(p.margin_used),
                    "short_proceeds": str(p.short_proceeds),
                    "agent_id": p.agent_id,
                    "orchestra_id": p.orchestra_id,
                    "strategy_id": p.strategy_id,
                    "strategy_version": p.strategy_version,
                    "opened_at": p.opened_at,
                    "updated_at": p.updated_at,
                }
                for sym, p in self.positions.items()
            },
        }

    @classmethod
    def deserialize(cls, raw: dict[str, Any]) -> "PortfolioBook":
        book = cls(
            portfolio_id=str(raw["portfolio_id"]),
            cash=money(raw.get("cash", 0)),
            reserved_cash=money(raw.get("reserved_cash", 0)),
            currency=str(raw.get("currency") or "USD"),
            shorting_enabled=bool(raw.get("shorting_enabled")),
            initial_margin_pct=D(raw.get("initial_margin_pct", 50)),
            maintenance_margin_pct=D(raw.get("maintenance_margin_pct", 30)),
            realized_pnl=money(raw.get("realized_pnl", 0)),
            fees_paid=money(raw.get("fees_paid", 0)),
            peak_equity=money(raw.get("peak_equity", 0)),
            closed_trades_won=int(raw.get("closed_trades_won") or 0),
            closed_trades_lost=int(raw.get("closed_trades_lost") or 0),
            closed_trades_flat=int(raw.get("closed_trades_flat") or 0),
        )
        for rid, amt in (raw.get("reservations") or {}).items():
            book.reservations[str(rid)] = money(amt)
        for sym, p in (raw.get("positions") or {}).items():
            book.positions[sym.upper()] = PositionState(
                symbol=str(p.get("symbol") or sym).upper(),
                side=str(p.get("side") or "LONG"),
                qty=money(p.get("qty", 0)),
                avg_entry=money(p.get("avg_entry", 0)),
                realized_pnl=money(p.get("realized_pnl", 0)),
                fees=money(p.get("fees", 0)),
                margin_used=money(p.get("margin_used", 0)),
                short_proceeds=money(p.get("short_proceeds", 0)),
                agent_id=p.get("agent_id"),
                orchestra_id=p.get("orchestra_id"),
                strategy_id=p.get("strategy_id"),
                strategy_version=p.get("strategy_version"),
                opened_at=str(p.get("opened_at") or ""),
                updated_at=str(p.get("updated_at") or ""),
                position_id=str(p.get("position_id") or uuid.uuid4()),
            )
        return book
