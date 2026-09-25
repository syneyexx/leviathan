"""Strict causality clock and epistemic time firewall — no future information access."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .types import Bar, CausalityViolation


def parse_as_of(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 (or Z) timestamp to aware UTC datetime. None if empty/invalid."""
    text = str(raw or "").strip()
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compare_ts(a: str, b: str) -> int:
    """Compare two timestamps. Returns -1 / 0 / 1. Falls back to lexicographic only if unparseable."""
    da, db = parse_as_of(a), parse_as_of(b)
    if da is not None and db is not None:
        if da < db:
            return -1
        if da > db:
            return 1
        return 0
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def ts_available(available_at: str | None, as_of: str) -> bool:
    """True iff available_at is missing (timeless) or available_at <= as_of."""
    if available_at is None or str(available_at).strip() == "":
        return True
    return compare_ts(str(available_at), as_of) <= 0


@dataclass
class SimulationClock:
    """Single source of truth for simulated time.

    At bar index i, only bars[0..i] inclusive are observable.
    Any attempt to read index > i fails hard.
    """

    bars: Sequence[Bar]
    index: int = -1  # before first bar
    violations: int = 0

    @property
    def current_ts(self) -> str | None:
        if self.index < 0 or self.index >= len(self.bars):
            return None
        return self.bars[self.index].ts

    @property
    def current_bar(self) -> Bar | None:
        if self.index < 0 or self.index >= len(self.bars):
            return None
        return self.bars[self.index]

    @property
    def done(self) -> bool:
        return self.index >= len(self.bars) - 1 and len(self.bars) > 0 and self.index >= 0

    def advance(self) -> Bar | None:
        if not self.bars:
            return None
        if self.index >= len(self.bars) - 1:
            return None
        self.index += 1
        return self.bars[self.index]

    def set_index(self, index: int) -> None:
        if index < -1 or index >= len(self.bars):
            raise CausalityViolation(f"Illegal clock index {index} (bar_count={len(self.bars)})")
        self.index = index

    def observe(self, at_index: int) -> Bar:
        """Return bar at_index if and only if at_index <= current index."""
        if self.index < 0:
            self.violations += 1
            raise CausalityViolation("No bars visible before clock starts")
        if at_index < 0 or at_index >= len(self.bars):
            self.violations += 1
            raise CausalityViolation(f"Bar index {at_index} out of range")
        if at_index > self.index:
            self.violations += 1
            raise CausalityViolation(
                f"Look-ahead refused: requested bar {at_index} while clock is at {self.index}"
            )
        return self.bars[at_index]

    def window(self, lookback: int) -> list[Bar]:
        """Causal rolling window ending at current bar (inclusive)."""
        if self.index < 0:
            self.violations += 1
            raise CausalityViolation("No window before clock starts")
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        start = max(0, self.index - lookback + 1)
        # Explicitly only slice up to index inclusive — never beyond.
        return [self.bars[i] for i in range(start, self.index + 1)]

    def closes(self, lookback: int) -> list[float]:
        return [b.close for b in self.window(lookback)]

    def market_view(self) -> "MarketView":
        return MarketView(clock=self)


@dataclass
class MarketView:
    """Bounded market observation surface for agents — never exposes future bars.

    Engine internals may still hold the full series on SimulationClock.bars;
    agents and strategies must use this view (or clock.observe / clock.window).
    """

    clock: SimulationClock

    @property
    def as_of(self) -> str | None:
        return self.clock.current_ts

    @property
    def index(self) -> int:
        return self.clock.index

    def current(self) -> Bar:
        bar = self.clock.current_bar
        if bar is None:
            self.clock.violations += 1
            raise CausalityViolation("No current bar before clock starts")
        return bar

    def history(self, window: int) -> list[Bar]:
        return self.clock.window(window)

    def closes(self, window: int) -> list[float]:
        return self.clock.closes(window)

    def bar_at(self, at_index: int) -> Bar:
        return self.clock.observe(at_index)

    def visible_count(self) -> int:
        return max(0, self.clock.index + 1)

    def has_future_access(self) -> bool:
        """Always False — future bars are unreachable through this API."""
        return False

    def __len__(self) -> int:
        return self.visible_count()


# Timestamp keys preferred for epistemic filtering (available_at is authoritative).
_AVAILABLE_KEYS = (
    "available_at",
    "availableAt",
    "publication_time",
    "published_at",
    "publishedAt",
    "received_at",
    "receivedAt",
)
_FALLBACK_TIME_KEYS = (
    "created_at",
    "createdAt",
    "updated_at",
    "updatedAt",
    "timestamp",
    "event_time",
    "eventTime",
)


def record_available_at(record: Mapping[str, Any]) -> str | None:
    """Extract the causal availability timestamp from a hit/record.

    Preference: available_at / publication / received. Timeless records
    (``timeless=True`` or ``knowledge_class=general``) return None (= always visible).
    """
    if record.get("timeless") is True:
        return None
    knowledge_class = str(record.get("knowledge_class") or record.get("knowledgeClass") or "").lower()
    if knowledge_class in {"general", "timeless", "concept"}:
        return None
    for key in _AVAILABLE_KEYS:
        value = record.get(key)
        if value:
            return str(value)
    meta = record.get("metadata")
    if isinstance(meta, dict):
        if meta.get("timeless") is True:
            return None
        for key in _AVAILABLE_KEYS:
            value = meta.get(key)
            if value:
                return str(value)
    for key in _FALLBACK_TIME_KEYS:
        value = record.get(key)
        if value:
            return str(value)
    if isinstance(meta, dict):
        for key in _FALLBACK_TIME_KEYS:
            value = meta.get(key)
            if value:
                return str(value)
    return None


@dataclass
class EpistemicFirewall:
    """Complete trading epistemic-time firewall for a historical (or live) as_of.

    Boundary: available_at <= as_of (not merely event_date <= as_of).
    Tracks violations for observability.
    """

    as_of: str
    violations: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    allow_untimestamped: bool = True

    def admit(self, record: Mapping[str, Any], *, source: str = "") -> bool:
        stamp = record_available_at(record)
        if stamp is None:
            if self.allow_untimestamped:
                return True
            self.violations += 1
            self.dropped.append({"source": source, "reason": "missing_available_at", "record": dict(record)})
            return False
        if ts_available(stamp, self.as_of):
            return True
        self.violations += 1
        self.dropped.append(
            {
                "source": source,
                "reason": "future_of_as_of",
                "available_at": stamp,
                "as_of": self.as_of,
            }
        )
        return False

    def filter_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        source: str = "",
    ) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for record in records:
            if self.admit(record, source=source):
                kept.append(dict(record))
        return kept

    def assert_no_future_ts(self, timestamps: Sequence[str]) -> None:
        assert_no_future(timestamps, self.as_of)

    def public_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "violations": self.violations,
            "dropped_count": len(self.dropped),
            "allow_untimestamped": self.allow_untimestamped,
            "truth": {
                "boundary": "available_at <= as_of",
                "event_date_alone_is_insufficient": True,
            },
        }


def assert_no_future(timestamps: Sequence[str], clock_ts: str) -> None:
    """Fail if any timestamp is strictly after the clock (datetime-aware)."""
    for ts in timestamps:
        if compare_ts(ts, clock_ts) > 0:
            raise CausalityViolation(f"Event {ts} is after clock {clock_ts}")


def filter_by_as_of(
    records: Sequence[Mapping[str, Any]],
    as_of: str,
    *,
    source: str = "",
) -> list[dict[str, Any]]:
    """Convenience: keep only records with available_at <= as_of."""
    return EpistemicFirewall(as_of=as_of).filter_records(records, source=source)
