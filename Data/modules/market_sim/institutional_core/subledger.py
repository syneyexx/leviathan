"""W42 — Subledger journaling for cash / lots / PnL / valuation.

Extends accounting.WalletLedger and portefeuille PortfolioBook — journal layer only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


JOURNAL_ACCOUNTS: tuple[str, ...] = (
    "cash",
    "lots",
    "realized_pnl",
    "unrealized_pnl",
    "fees",
    "valuation",
    "collateral",
)


@dataclass(frozen=True)
class JournalLine:
    account: str
    amount: float  # signed; debit-positive convention for asset accounts
    currency: str = "USD"
    instrument_id: str | None = None
    lot_id: str | None = None
    memo: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "amount": self.amount,
            "currency": self.currency,
            "instrumentId": self.instrument_id,
            "lotId": self.lot_id,
            "memo": self.memo,
        }


@dataclass
class JournalEntry:
    entry_id: str
    ts: str
    kind: str  # TRADE | FEE | VALUATION | CA_ADJUST | TRANSFER | MANUAL
    lines: list[JournalLine]
    refs: dict[str, str] = field(default_factory=dict)
    status: str = MeasurementState.OBSERVED.value

    def balanced(self, *, tol: float = 1e-8) -> bool:
        return abs(sum(line.amount for line in self.lines)) <= tol

    def public_dict(self) -> dict[str, Any]:
        return {
            "entryId": self.entry_id,
            "ts": self.ts,
            "kind": self.kind,
            "lines": [line.public_dict() for line in self.lines],
            "refs": dict(self.refs),
            "balanced": self.balanced(),
            "status": self.status,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "unbalanced_entry_is_not_silently_accepted": True,
            },
        }


@dataclass
class SubledgerBalances:
    balances: dict[str, float]
    by_instrument: dict[str, dict[str, float]] = field(default_factory=dict)
    entry_count: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "balances": dict(self.balances),
            "byInstrument": {k: dict(v) for k, v in self.by_instrument.items()},
            "entryCount": self.entry_count,
            "truth": DEFAULT_TRUTH.public_dict(),
        }


class Subledger:
    """Double-entry style journal with balance rollups."""

    def __init__(self, *, currency: str = "USD") -> None:
        self.currency = currency
        self._entries: list[JournalEntry] = []

    def post(self, entry: JournalEntry, *, require_balanced: bool = True) -> JournalEntry:
        for line in entry.lines:
            if line.account not in JOURNAL_ACCOUNTS:
                raise ValueError(f"unknown journal account: {line.account}")
        if require_balanced and not entry.balanced():
            raise ValueError(f"unbalanced journal entry: {entry.entry_id}")
        self._entries.append(entry)
        return entry

    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def balances(self) -> SubledgerBalances:
        bals: dict[str, float] = {a: 0.0 for a in JOURNAL_ACCOUNTS}
        by_inst: dict[str, dict[str, float]] = {}
        for entry in self._entries:
            for line in entry.lines:
                bals[line.account] = bals.get(line.account, 0.0) + line.amount
                if line.instrument_id:
                    bucket = by_inst.setdefault(line.instrument_id, {})
                    bucket[line.account] = bucket.get(line.account, 0.0) + line.amount
        return SubledgerBalances(balances=bals, by_instrument=by_inst, entry_count=len(self._entries))

    def public_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "entries": [e.public_dict() for e in self._entries],
            "balances": self.balances().public_dict(),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_accounting_wallet": True,
            },
        }


def trade_entry(
    *,
    entry_id: str,
    ts: str,
    instrument_id: str,
    lot_id: str,
    qty: float,
    price: float,
    fee: float = 0.0,
    side: str = "BUY",
) -> JournalEntry:
    """Build a balanced trade journal entry (cash vs lots ± fees)."""
    notional = abs(qty) * price
    lines: list[JournalLine] = []
    if side.upper() in {"BUY", "COVER"}:
        lines.append(JournalLine("lots", notional, instrument_id=instrument_id, lot_id=lot_id))
        lines.append(JournalLine("cash", -notional, instrument_id=instrument_id, lot_id=lot_id))
    else:
        lines.append(JournalLine("cash", notional, instrument_id=instrument_id, lot_id=lot_id))
        lines.append(JournalLine("lots", -notional, instrument_id=instrument_id, lot_id=lot_id))
    if fee:
        lines.append(JournalLine("fees", fee, instrument_id=instrument_id))
        lines.append(JournalLine("cash", -fee, instrument_id=instrument_id))
    return JournalEntry(entry_id=entry_id, ts=ts, kind="TRADE", lines=lines, refs={"side": side.upper()})


def valuation_entry(
    *,
    entry_id: str,
    ts: str,
    instrument_id: str,
    mark_delta: float,
) -> JournalEntry:
    """Mark-to-market: unrealized_pnl vs valuation (balanced)."""
    return JournalEntry(
        entry_id=entry_id,
        ts=ts,
        kind="VALUATION",
        lines=[
            JournalLine("unrealized_pnl", mark_delta, instrument_id=instrument_id),
            JournalLine("valuation", -mark_delta, instrument_id=instrument_id),
        ],
    )


def realize_pnl_entry(
    *,
    entry_id: str,
    ts: str,
    instrument_id: str,
    lot_id: str,
    pnl: float,
) -> JournalEntry:
    return JournalEntry(
        entry_id=entry_id,
        ts=ts,
        kind="TRADE",
        lines=[
            JournalLine("realized_pnl", pnl, instrument_id=instrument_id, lot_id=lot_id),
            JournalLine("lots", -pnl, instrument_id=instrument_id, lot_id=lot_id),
        ],
        refs={"lotId": lot_id},
    )


def replay_balances(entries: Sequence[JournalEntry | Mapping[str, Any]]) -> SubledgerBalances:
    ledger = Subledger()
    for raw in entries:
        if isinstance(raw, JournalEntry):
            ledger.post(raw)
        else:
            lines = [
                JournalLine(
                    account=str(line.get("account")),
                    amount=float(line.get("amount") or 0),
                    currency=str(line.get("currency") or "USD"),
                    instrument_id=line.get("instrumentId") or line.get("instrument_id"),
                    lot_id=line.get("lotId") or line.get("lot_id"),
                    memo=str(line.get("memo") or ""),
                )
                for line in (raw.get("lines") or [])
            ]
            ledger.post(
                JournalEntry(
                    entry_id=str(raw.get("entry_id") or raw.get("entryId")),
                    ts=str(raw.get("ts") or ""),
                    kind=str(raw.get("kind") or "MANUAL"),
                    lines=lines,
                    refs=dict(raw.get("refs") or {}),
                )
            )
    return ledger.balances()
