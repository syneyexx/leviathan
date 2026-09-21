"""Money and position ledger.

Every booking is a ``Decimal`` and every booking is idempotent: applying the same
``source_event_id`` twice is a no-op. That property is what makes retries, restarts and
replay safe — the legacy paper service had no such key, so a retried run could double-book.

Two settlement styles, because conflating them is how backtests end up wrong:

``funded``
    The full notional is exchanged (crypto spot, equity, ETF, bond, option premium).
    Equity counts cash plus the signed market value of the position.

``margin``
    No notional is exchanged; the position consumes margin and produces mark-to-market
    profit and loss (futures, perpetuals, CFDs, leveraged FX).
    Equity counts cash plus unrealised profit and loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Literal

from trading_lab.contracts import (
    FillEvent,
    InstrumentSpec,
    PortfolioSnapshot,
    PositionSnapshot,
    quantize_money,
    to_decimal,
)

SettlementStyle = Literal["funded", "margin"]

ZERO = Decimal("0")


@dataclass
class LedgerEntry:
    source_event_id: str
    sequence: int
    event_time: str
    account: str
    currency: str
    amount: Decimal
    kind: str
    instrument_id: str | None = None
    memo: str = ""

    def as_row(self) -> dict[str, Any]:
        return {
            "source_event_id": self.source_event_id,
            "sequence": self.sequence,
            "event_time": self.event_time,
            "account": self.account,
            "currency": self.currency,
            "amount": str(self.amount),
            "kind": self.kind,
            "instrument_id": self.instrument_id,
            "memo": self.memo,
        }


@dataclass
class Position:
    instrument_id: str
    signed_quantity: Decimal = ZERO
    average_price: Decimal = ZERO
    multiplier: Decimal = Decimal("1")
    settlement_style: SettlementStyle = "funded"
    realized_pnl: Decimal = ZERO
    mark_price: Decimal | None = None
    mark_event_time: str = ""
    opened_at: str = ""
    currency: str = "USD"
    margin_used: Decimal = ZERO
    accrued_interest: Decimal = ZERO
    fees_paid: Decimal = ZERO
    funding_paid: Decimal = ZERO
    borrow_paid: Decimal = ZERO

    @property
    def quantity(self) -> Decimal:
        return abs(self.signed_quantity)

    @property
    def side(self) -> str:
        if self.signed_quantity > 0:
            return "long"
        if self.signed_quantity < 0:
            return "short"
        return "flat"

    @property
    def is_flat(self) -> bool:
        return self.signed_quantity == 0

    def market_value(self) -> Decimal:
        if self.mark_price is None:
            return ZERO
        return self.signed_quantity * self.mark_price * self.multiplier

    def unrealized_pnl(self) -> Decimal:
        if self.mark_price is None or self.signed_quantity == 0:
            return ZERO
        return self.signed_quantity * (self.mark_price - self.average_price) * self.multiplier

    def notional(self) -> Decimal:
        price = self.mark_price if self.mark_price is not None else self.average_price
        return abs(self.signed_quantity) * abs(price) * self.multiplier

    def as_snapshot(self) -> PositionSnapshot:
        return PositionSnapshot(
            instrument_id=self.instrument_id,
            side="long" if self.signed_quantity >= 0 else "short",
            quantity=self.quantity,
            average_price=self.average_price,
            multiplier=self.multiplier,
            mark_price=self.mark_price,
            unrealized_pnl=quantize_money(self.unrealized_pnl()),
            realized_pnl=quantize_money(self.realized_pnl),
            margin_used=quantize_money(self.margin_used),
            borrow_liability=quantize_money(
                abs(self.market_value()) if self.settlement_style == "funded" and self.signed_quantity < 0 else ZERO
            ),
            opened_at=self.opened_at,
            currency=self.currency,
        )


class Portfolio:
    """Multi-currency ledger with idempotent bookings and explicit reconciliation."""

    def __init__(
        self,
        *,
        base_currency: str = "USD",
        starting_cash: dict[str, Decimal] | None = None,
    ) -> None:
        self.base_currency = base_currency.upper()
        self.cash: dict[str, Decimal] = {}
        self.reserved: dict[str, Decimal] = {}
        self.positions: dict[str, Position] = {}
        self.fx_rates: dict[str, Decimal] = {self.base_currency: Decimal("1")}
        self.fees_paid: Decimal = ZERO
        self.funding_paid: Decimal = ZERO
        self.borrow_paid: Decimal = ZERO
        self.realized_pnl: Decimal = ZERO
        self.entries: list[LedgerEntry] = []
        self._applied_events: set[str] = set()
        self._sequence: int = 0
        self.valuation_warnings: list[str] = []
        for currency, amount in (starting_cash or {"USD": Decimal("0")}).items():
            self.cash[currency.upper()] = to_decimal(amount)

    # --- idempotency -------------------------------------------------------------

    def already_applied(self, event_id: str) -> bool:
        return event_id in self._applied_events

    def mark_applied(self, event_id: str) -> None:
        self._applied_events.add(event_id)

    # --- cash --------------------------------------------------------------------

    def balance(self, currency: str) -> Decimal:
        return self.cash.get(currency.upper(), ZERO)

    def available(self, currency: str) -> Decimal:
        key = currency.upper()
        return self.cash.get(key, ZERO) - self.reserved.get(key, ZERO)

    def reserve(self, currency: str, amount: Decimal) -> None:
        key = currency.upper()
        self.reserved[key] = self.reserved.get(key, ZERO) + to_decimal(amount)

    def release(self, currency: str, amount: Decimal) -> None:
        key = currency.upper()
        remaining = self.reserved.get(key, ZERO) - to_decimal(amount)
        self.reserved[key] = remaining if remaining > 0 else ZERO

    def _book(
        self,
        *,
        source_event_id: str,
        event_time: str,
        account: str,
        currency: str,
        amount: Decimal,
        kind: str,
        instrument_id: str | None = None,
        memo: str = "",
    ) -> LedgerEntry:
        key = currency.upper()
        entry = LedgerEntry(
            source_event_id=source_event_id,
            sequence=self._sequence,
            event_time=event_time,
            account=account,
            currency=key,
            amount=to_decimal(amount),
            kind=kind,
            instrument_id=instrument_id,
            memo=memo,
        )
        self._sequence += 1
        self.entries.append(entry)
        if account == "cash":
            self.cash[key] = self.cash.get(key, ZERO) + entry.amount
        return entry

    # --- positions ---------------------------------------------------------------

    def position(self, instrument_id: str) -> Position | None:
        return self.positions.get(instrument_id)

    def ensure_position(self, spec: InstrumentSpec, settlement_style: SettlementStyle) -> Position:
        existing = self.positions.get(spec.instrument_id)
        if existing is not None:
            return existing
        position = Position(
            instrument_id=spec.instrument_id,
            multiplier=spec.multiplier,
            settlement_style=settlement_style,
            currency=spec.settle_currency.upper(),
        )
        self.positions[spec.instrument_id] = position
        return position

    def apply_fill(
        self,
        fill: FillEvent,
        spec: InstrumentSpec,
        *,
        settlement_style: SettlementStyle,
        cash_notional: Decimal | None = None,
        accrued_interest: Decimal = ZERO,
    ) -> list[LedgerEntry]:
        """Book one fill. Returns the ledger entries written (empty on idempotent replay).

        ``cash_notional`` lets an instrument adapter override the exchanged amount, which is
        how a bond books a dirty price while quoting clean.
        """
        if self.already_applied(fill.event_id):
            return []
        position = self.ensure_position(spec, settlement_style)
        signed_delta = fill.quantity if fill.side == "buy" else -fill.quantity
        price = fill.price
        multiplier = spec.multiplier
        written: list[LedgerEntry] = []

        realized = self._apply_trade(position, signed_delta, price, multiplier)
        position.realized_pnl += realized
        self.realized_pnl += realized
        if position.opened_at == "" and not position.is_flat:
            position.opened_at = fill.event_time
        if position.is_flat:
            position.average_price = ZERO
            position.margin_used = ZERO

        settle_currency = spec.settle_currency.upper()
        if settlement_style == "funded":
            notional = cash_notional if cash_notional is not None else (signed_delta * price * multiplier)
            written.append(
                self._book(
                    source_event_id=fill.event_id,
                    event_time=fill.event_time,
                    account="cash",
                    currency=settle_currency,
                    amount=-notional,
                    kind="fill_notional",
                    instrument_id=spec.instrument_id,
                    memo=f"{fill.side} {fill.quantity} @ {price}",
                )
            )
            if accrued_interest != ZERO:
                written.append(
                    self._book(
                        source_event_id=fill.event_id,
                        event_time=fill.event_time,
                        account="cash",
                        currency=settle_currency,
                        amount=-accrued_interest,
                        kind="accrued_interest",
                        instrument_id=spec.instrument_id,
                        memo="accrued interest paid to seller" if signed_delta > 0 else "accrued interest received",
                    )
                )
                position.accrued_interest += accrued_interest if signed_delta > 0 else -accrued_interest
        else:
            if realized != ZERO:
                written.append(
                    self._book(
                        source_event_id=fill.event_id,
                        event_time=fill.event_time,
                        account="cash",
                        currency=settle_currency,
                        amount=realized,
                        kind="realized_pnl",
                        instrument_id=spec.instrument_id,
                        memo="margin-settled realised profit and loss",
                    )
                )

        if fill.fee != ZERO:
            fee_currency = (fill.fee_currency or settle_currency).upper()
            written.append(
                self._book(
                    source_event_id=fill.event_id,
                    event_time=fill.event_time,
                    account="cash",
                    currency=fee_currency,
                    amount=-fill.fee,
                    kind="fee",
                    instrument_id=spec.instrument_id,
                    memo=f"{fill.liquidity} fee",
                )
            )
            written.append(
                self._book(
                    source_event_id=fill.event_id,
                    event_time=fill.event_time,
                    account="fees",
                    currency=fee_currency,
                    amount=fill.fee,
                    kind="fee",
                    instrument_id=spec.instrument_id,
                )
            )
            self.fees_paid += fill.fee
            position.fees_paid += fill.fee

        if realized != ZERO:
            written.append(
                self._book(
                    source_event_id=fill.event_id,
                    event_time=fill.event_time,
                    account="realized_pnl",
                    currency=settle_currency,
                    amount=realized,
                    kind="realized_pnl",
                    instrument_id=spec.instrument_id,
                )
            )

        self.mark_applied(fill.event_id)
        return written

    @staticmethod
    def _apply_trade(
        position: Position,
        signed_delta: Decimal,
        price: Decimal,
        multiplier: Decimal,
    ) -> Decimal:
        """Weighted-average position update. Returns realised profit and loss."""
        old = position.signed_quantity
        new = old + signed_delta
        realized = ZERO
        if old == 0 or (old > 0) == (signed_delta > 0):
            total = abs(old) + abs(signed_delta)
            if total > 0:
                position.average_price = (
                    position.average_price * abs(old) + price * abs(signed_delta)
                ) / total
        else:
            closed = min(abs(old), abs(signed_delta))
            direction = Decimal("1") if old > 0 else Decimal("-1")
            realized = closed * (price - position.average_price) * direction * multiplier
            if abs(signed_delta) > abs(old):
                position.average_price = price
        position.signed_quantity = new
        return realized

    def apply_cash_flow(
        self,
        *,
        source_event_id: str,
        event_time: str,
        currency: str,
        amount: Decimal,
        kind: str,
        instrument_id: str | None = None,
        memo: str = "",
    ) -> list[LedgerEntry]:
        """Funding, borrow fees, coupons, dividends and settlements. Idempotent."""
        if self.already_applied(source_event_id):
            return []
        entries = [
            self._book(
                source_event_id=source_event_id,
                event_time=event_time,
                account="cash",
                currency=currency,
                amount=amount,
                kind=kind,
                instrument_id=instrument_id,
                memo=memo,
            )
        ]
        bucket = {"funding": "funding", "borrow_fee": "borrow", "financing": "borrow"}.get(kind)
        if bucket:
            entries.append(
                self._book(
                    source_event_id=source_event_id,
                    event_time=event_time,
                    account=bucket,
                    currency=currency,
                    amount=-amount,
                    kind=kind,
                    instrument_id=instrument_id,
                )
            )
            if bucket == "funding":
                self.funding_paid += -amount
                if instrument_id and instrument_id in self.positions:
                    self.positions[instrument_id].funding_paid += -amount
            else:
                self.borrow_paid += -amount
                if instrument_id and instrument_id in self.positions:
                    self.positions[instrument_id].borrow_paid += -amount
        self.mark_applied(source_event_id)
        return entries

    def adjust_position_for_corporate_action(
        self,
        instrument_id: str,
        *,
        quantity_factor: Decimal,
        price_factor: Decimal,
    ) -> bool:
        """Apply a split/reverse-split to an open position without changing its value."""
        position = self.positions.get(instrument_id)
        if position is None or position.is_flat:
            return False
        if quantity_factor <= 0 or price_factor <= 0:
            raise ValueError("corporate_action_factors_must_be_positive")
        position.signed_quantity = position.signed_quantity * quantity_factor
        position.average_price = position.average_price * price_factor
        if position.mark_price is not None:
            position.mark_price = position.mark_price * price_factor
        return True

    # --- valuation ---------------------------------------------------------------

    def set_fx_rate(self, currency: str, rate: Decimal) -> None:
        self.fx_rates[currency.upper()] = to_decimal(rate)

    def mark(self, instrument_id: str, price: Decimal, event_time: str) -> None:
        position = self.positions.get(instrument_id)
        if position is None:
            return
        position.mark_price = to_decimal(price)
        position.mark_event_time = event_time

    def set_margin(self, instrument_id: str, amount: Decimal) -> None:
        position = self.positions.get(instrument_id)
        if position is not None:
            position.margin_used = to_decimal(amount)

    def convert(self, currency: str, amount: Decimal) -> Decimal | None:
        key = currency.upper()
        if key == self.base_currency:
            return amount
        rate = self.fx_rates.get(key)
        if rate is None:
            return None
        return amount * rate

    def equity(self) -> tuple[Decimal, list[str]]:
        total = ZERO
        unconverted: list[str] = []
        for currency, amount in self.cash.items():
            converted = self.convert(currency, amount)
            if converted is None:
                if amount != ZERO:
                    unconverted.append(f"{currency}:{amount}")
                continue
            total += converted
        for position in self.positions.values():
            if position.is_flat:
                continue
            component = (
                position.market_value()
                if position.settlement_style == "funded"
                else position.unrealized_pnl()
            )
            converted = self.convert(position.currency, component)
            if converted is None:
                unconverted.append(f"{position.instrument_id}:{position.currency}")
                continue
            total += converted
        return total, unconverted

    def gross_exposure(self) -> Decimal:
        total = ZERO
        for position in self.positions.values():
            converted = self.convert(position.currency, position.notional())
            total += converted if converted is not None else ZERO
        return total

    def net_exposure(self) -> Decimal:
        total = ZERO
        for position in self.positions.values():
            signed = position.notional() * (Decimal("1") if position.signed_quantity >= 0 else Decimal("-1"))
            converted = self.convert(position.currency, signed)
            total += converted if converted is not None else ZERO
        return total

    def margin_used(self) -> Decimal:
        total = ZERO
        for position in self.positions.values():
            converted = self.convert(position.currency, position.margin_used)
            total += converted if converted is not None else ZERO
        return total

    def unrealized_pnl(self) -> Decimal:
        total = ZERO
        for position in self.positions.values():
            converted = self.convert(position.currency, position.unrealized_pnl())
            total += converted if converted is not None else ZERO
        return total

    def liabilities(self) -> Decimal:
        total = ZERO
        for position in self.positions.values():
            if position.settlement_style == "funded" and position.signed_quantity < 0:
                converted = self.convert(position.currency, abs(position.market_value()))
                total += converted if converted is not None else ZERO
        return total

    def snapshot(self, as_of: str, *, valuation_source: str = "mark") -> PortfolioSnapshot:
        equity, unconverted = self.equity()
        stale = [
            position.instrument_id
            for position in self.positions.values()
            if not position.is_flat and position.mark_price is None
        ]
        return PortfolioSnapshot(
            as_of=as_of,
            base_currency=self.base_currency,
            cash={currency: quantize_money(amount) for currency, amount in sorted(self.cash.items())},
            reserved_cash={
                currency: quantize_money(amount)
                for currency, amount in sorted(self.reserved.items())
                if amount != ZERO
            },
            positions=[
                position.as_snapshot() for position in self.positions.values() if not position.is_flat
            ],
            fees_paid=quantize_money(self.fees_paid),
            funding_paid=quantize_money(self.funding_paid),
            borrow_paid=quantize_money(self.borrow_paid),
            realized_pnl=quantize_money(self.realized_pnl),
            unrealized_pnl=quantize_money(self.unrealized_pnl()),
            equity=quantize_money(equity),
            gross_exposure=quantize_money(self.gross_exposure()),
            net_exposure=quantize_money(self.net_exposure()),
            margin_used=quantize_money(self.margin_used()),
            liabilities=quantize_money(self.liabilities()),
            valuation_source=valuation_source,
            stale_marks=sorted(set(stale) | set(unconverted)),
        )

    # --- reconciliation ----------------------------------------------------------

    def reconcile(self) -> dict[str, Any]:
        """Recompute cash from the append-only ledger and compare with live balances.

        Any mismatch is a bug in the booking path, so this returns structured failure state
        rather than raising: the caller records it on the run.
        """
        rebuilt: dict[str, Decimal] = {}
        for entry in self.entries:
            if entry.account != "cash":
                continue
            rebuilt[entry.currency] = rebuilt.get(entry.currency, ZERO) + entry.amount
        opening: dict[str, Decimal] = {}
        for currency, amount in self.cash.items():
            opening[currency] = amount - rebuilt.get(currency, ZERO)
        mismatches: list[dict[str, str]] = []
        for currency in sorted(set(self.cash) | set(rebuilt)):
            expected = opening.get(currency, ZERO) + rebuilt.get(currency, ZERO)
            actual = self.cash.get(currency, ZERO)
            if expected != actual:
                mismatches.append(
                    {"currency": currency, "expected": str(expected), "actual": str(actual)}
                )
        fee_total = sum(
            (entry.amount for entry in self.entries if entry.account == "fees"), ZERO
        )
        realized_total = sum(
            (entry.amount for entry in self.entries if entry.account == "realized_pnl"), ZERO
        )
        if fee_total != self.fees_paid:
            mismatches.append({"currency": "fees", "expected": str(fee_total), "actual": str(self.fees_paid)})
        if realized_total != self.realized_pnl:
            mismatches.append(
                {"currency": "realized_pnl", "expected": str(realized_total), "actual": str(self.realized_pnl)}
            )
        return {
            "ok": not mismatches,
            "entries": len(self.entries),
            "applied_events": len(self._applied_events),
            "mismatches": mismatches,
            "cash": {currency: str(amount) for currency, amount in sorted(self.cash.items())},
        }

    # --- persistence -------------------------------------------------------------

    def drain_entries(self) -> list[LedgerEntry]:
        """Hand over pending entries for durable append-only storage."""
        pending, self.entries = self.entries, []
        return pending

    def state(self) -> dict[str, Any]:
        return {
            "base_currency": self.base_currency,
            "cash": {currency: str(amount) for currency, amount in self.cash.items()},
            "reserved": {currency: str(amount) for currency, amount in self.reserved.items()},
            "fx_rates": {currency: str(rate) for currency, rate in self.fx_rates.items()},
            "fees_paid": str(self.fees_paid),
            "funding_paid": str(self.funding_paid),
            "borrow_paid": str(self.borrow_paid),
            "realized_pnl": str(self.realized_pnl),
            "sequence": self._sequence,
            "applied_events": sorted(self._applied_events),
            "positions": [
                {
                    "instrument_id": position.instrument_id,
                    "signed_quantity": str(position.signed_quantity),
                    "average_price": str(position.average_price),
                    "multiplier": str(position.multiplier),
                    "settlement_style": position.settlement_style,
                    "realized_pnl": str(position.realized_pnl),
                    "mark_price": None if position.mark_price is None else str(position.mark_price),
                    "mark_event_time": position.mark_event_time,
                    "opened_at": position.opened_at,
                    "currency": position.currency,
                    "margin_used": str(position.margin_used),
                    "accrued_interest": str(position.accrued_interest),
                    "fees_paid": str(position.fees_paid),
                    "funding_paid": str(position.funding_paid),
                    "borrow_paid": str(position.borrow_paid),
                }
                for position in self.positions.values()
            ],
        }

    @classmethod
    def restore(cls, state: dict[str, Any]) -> "Portfolio":
        portfolio = cls(base_currency=state.get("base_currency", "USD"))
        portfolio.cash = {key: to_decimal(value) for key, value in (state.get("cash") or {}).items()}
        portfolio.reserved = {key: to_decimal(value) for key, value in (state.get("reserved") or {}).items()}
        portfolio.fx_rates = {key: to_decimal(value) for key, value in (state.get("fx_rates") or {}).items()}
        portfolio.fees_paid = to_decimal(state.get("fees_paid", "0"))
        portfolio.funding_paid = to_decimal(state.get("funding_paid", "0"))
        portfolio.borrow_paid = to_decimal(state.get("borrow_paid", "0"))
        portfolio.realized_pnl = to_decimal(state.get("realized_pnl", "0"))
        portfolio._sequence = int(state.get("sequence", 0))
        portfolio._applied_events = set(state.get("applied_events") or [])
        for payload in state.get("positions") or []:
            position = Position(
                instrument_id=payload["instrument_id"],
                signed_quantity=to_decimal(payload["signed_quantity"]),
                average_price=to_decimal(payload["average_price"]),
                multiplier=to_decimal(payload["multiplier"]),
                settlement_style=payload.get("settlement_style", "funded"),
                realized_pnl=to_decimal(payload.get("realized_pnl", "0")),
                mark_price=None if payload.get("mark_price") is None else to_decimal(payload["mark_price"]),
                mark_event_time=payload.get("mark_event_time", ""),
                opened_at=payload.get("opened_at", ""),
                currency=payload.get("currency", portfolio.base_currency),
                margin_used=to_decimal(payload.get("margin_used", "0")),
                accrued_interest=to_decimal(payload.get("accrued_interest", "0")),
                fees_paid=to_decimal(payload.get("fees_paid", "0")),
                funding_paid=to_decimal(payload.get("funding_paid", "0")),
                borrow_paid=to_decimal(payload.get("borrow_paid", "0")),
            )
            portfolio.positions[position.instrument_id] = position
        return portfolio


def ledger_rows(entries: Iterable[LedgerEntry]) -> list[dict[str, Any]]:
    return [entry.as_row() for entry in entries]


__all__ = ["LedgerEntry", "Portfolio", "Position", "SettlementStyle", "ZERO", "ledger_rows"]
