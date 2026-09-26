"""Point-in-time universe membership — no survivorship bias by default (W13A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class MembershipEventKind(str, Enum):
    LISTED = "LISTED"  # IPO / listing
    DELISTED = "DELISTED"
    RENAMED = "RENAMED"  # symbol change
    EXCHANGE_CHANGE = "EXCHANGE_CHANGE"


@dataclass(frozen=True)
class MembershipEvent:
    symbol: str
    kind: MembershipEventKind
    effective_at: str  # ISO-8601 causal availability
    new_symbol: str | None = None
    exchange: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind.value,
            "effective_at": self.effective_at,
            "new_symbol": self.new_symbol,
            "exchange": self.exchange,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    kind: str  # split | dividend | symbol_change
    effective_at: str
    factor: float | None = None  # split factor (e.g. 2.0 for 2-for-1)
    cash_amount: float | None = None  # dividend per share
    new_symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "effective_at": self.effective_at,
            "factor": self.factor,
            "cash_amount": self.cash_amount,
            "new_symbol": self.new_symbol,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SessionCalendarDay:
    date: str  # YYYY-MM-DD in exchange timezone
    session: str  # open | holiday | half_day
    open_ts: str | None = None
    close_ts: str | None = None
    exchange: str = ""
    timezone: str = "UTC"

    def public_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "session": self.session,
            "open_ts": self.open_ts,
            "close_ts": self.close_ts,
            "exchange": self.exchange,
            "timezone": self.timezone,
        }


@dataclass
class DatasetRevisionIdentity:
    """Causal revision identity for datasets where revisions matter (W13A)."""

    revision_id: str
    published_at: str
    available_at: str
    observed_at: str
    content_hash: str
    parent_revision_id: str | None = None
    survivorship_mode: str = "point_in_time"  # point_in_time | survivors_only | labelled_today_universe

    def public_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "observed_at": self.observed_at,
            "content_hash": self.content_hash,
            "parent_revision_id": self.parent_revision_id,
            "survivorship_mode": self.survivorship_mode,
            "truth": {
                "today_universe_is_not_historical_by_default": self.survivorship_mode
                != "labelled_today_universe",
                "survivorship_bias_must_be_labelled": True,
            },
        }


class PointInTimeUniverse:
    """Causal membership — delisted assets do not silently disappear from history."""

    def __init__(
        self,
        events: Sequence[MembershipEvent] | None = None,
        *,
        corporate_actions: Sequence[CorporateAction] | None = None,
        calendar: Sequence[SessionCalendarDay] | None = None,
        survivorship_mode: str = "point_in_time",
    ) -> None:
        self.events = sorted(list(events or []), key=lambda e: (e.effective_at, e.symbol, e.kind.value))
        self.corporate_actions = sorted(
            list(corporate_actions or []), key=lambda a: (a.effective_at, a.symbol)
        )
        self.calendar = list(calendar or [])
        self.survivorship_mode = survivorship_mode

    def as_of_membership(self, as_of: str) -> set[str]:
        """Symbols that are listed and not yet delisted as of timestamp."""
        if self.survivorship_mode == "survivors_only":
            # Contaminated mode: only symbols that never delist (or delist after "now").
            # Explicitly labelled — not default.
            active: set[str] = set()
            delisted_forever: set[str] = set()
            for ev in self.events:
                if ev.kind == MembershipEventKind.LISTED:
                    active.add(ev.symbol)
                elif ev.kind == MembershipEventKind.DELISTED:
                    delisted_forever.add(ev.symbol)
                    active.discard(ev.symbol)
                elif ev.kind == MembershipEventKind.RENAMED and ev.new_symbol:
                    active.discard(ev.symbol)
                    active.add(ev.new_symbol)
            return active - delisted_forever

        active: set[str] = set()
        for ev in self.events:
            if ev.effective_at > as_of:
                break
            if ev.kind == MembershipEventKind.LISTED:
                active.add(ev.symbol)
            elif ev.kind == MembershipEventKind.DELISTED:
                active.discard(ev.symbol)
            elif ev.kind == MembershipEventKind.RENAMED and ev.new_symbol:
                if ev.symbol in active:
                    active.discard(ev.symbol)
                    active.add(ev.new_symbol)
        return active

    def resolve_symbol(self, symbol: str, as_of: str) -> str:
        """Follow rename chain causally up to as_of."""
        current = symbol
        for ev in self.events:
            if ev.effective_at > as_of:
                break
            if ev.kind == MembershipEventKind.RENAMED and ev.symbol == current and ev.new_symbol:
                current = ev.new_symbol
        return current

    def corporate_actions_as_of(self, symbol: str, as_of: str) -> list[CorporateAction]:
        return [
            a
            for a in self.corporate_actions
            if a.symbol == symbol and a.effective_at <= as_of
        ]

    def is_trading_day(self, date: str, *, exchange: str = "") -> bool:
        for day in self.calendar:
            if day.date == date and (not exchange or day.exchange == exchange):
                return day.session in {"open", "half_day"}
        # No calendar entry ⇒ assume open (UNMEASURED calendar).
        return True

    def public_dict(self) -> dict[str, Any]:
        return {
            "events": [e.public_dict() for e in self.events],
            "corporate_actions": [a.public_dict() for a in self.corporate_actions],
            "calendar_days": [c.public_dict() for c in self.calendar],
            "survivorship_mode": self.survivorship_mode,
            "truth": {
                "point_in_time_default": self.survivorship_mode == "point_in_time",
                "delisted_do_not_silently_vanish_from_history": True,
                "today_universe_must_be_labelled": True,
            },
        }
