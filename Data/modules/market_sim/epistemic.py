"""Complete trading epistemic-time firewall.

Historical agents may only access information with ``available_at <= as_of``.
Event time alone is insufficient — publication / availability is the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .types import CausalityViolation, MarketSimError


class EvaluationWindow(str, Enum):
    """Chronological evaluation windows — never shuffle financial time."""

    RESEARCH = "RESEARCH"
    VALIDATION = "VALIDATION"
    SEALED_TEST = "SEALED_TEST"
    LIVE_SHADOW = "LIVE_SHADOW"
    LIVE_PAPER = "LIVE_PAPER"


# Keys inspected when resolving availability on heterogeneous records.
_AVAILABLE_AT_KEYS = (
    "available_at",
    "availableAt",
)
_FALLBACK_TIME_KEYS = (
    "publication_time",
    "published_at",
    "publishedAt",
    "received_at",
    "receivedAt",
    "provider_time",
    "providerTime",
    "created_at",
    "createdAt",
    "timestamp",
    "ts",
    "event_time",
    "eventTime",
)


def parse_ts(value: str | datetime | None) -> datetime | None:
    """Parse ISO / common market timestamps to timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise MarketSimError(
            "INVALID_TIMESTAMP",
            f"Cannot parse timestamp for causal compare: {text!r}",
            http_status=400,
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compare_ts(a: str | datetime, b: str | datetime) -> int:
    """Return -1 / 0 / 1 for a < b / a == b / a > b (UTC-aware)."""
    da = parse_ts(a)
    db = parse_ts(b)
    if da is None or db is None:
        raise MarketSimError("INVALID_TIMESTAMP", "Missing timestamp for causal compare")
    if da < db:
        return -1
    if da > db:
        return 1
    return 0


def is_available(*, available_at: str | datetime, as_of: str | datetime) -> bool:
    """True iff available_at <= as_of (the epistemic boundary)."""
    return compare_ts(available_at, as_of) <= 0


def resolve_available_at(record: Mapping[str, Any]) -> str | None:
    """Resolve the causal availability stamp from a heterogeneous record."""
    for key in _AVAILABLE_AT_KEYS:
        value = record.get(key)
        if value:
            return str(value)
    meta = record.get("metadata")
    if isinstance(meta, dict):
        for key in _AVAILABLE_AT_KEYS:
            value = meta.get(key)
            if value:
                return str(value)
    # Prefer max(publication, received) when both exist — information cannot
    # be known before it was published AND received.
    candidates: list[str] = []
    for key in _FALLBACK_TIME_KEYS:
        value = record.get(key)
        if value:
            candidates.append(str(value))
        if isinstance(meta, dict):
            mval = meta.get(key)
            if mval:
                candidates.append(str(mval))
    if not candidates:
        return None
    parsed = [(parse_ts(c), c) for c in candidates]
    parsed = [(dt, raw) for dt, raw in parsed if dt is not None]
    if not parsed:
        return None
    # Latest of known stamps is the conservative availability bound.
    parsed.sort(key=lambda item: item[0])
    return parsed[-1][1]


@dataclass(frozen=True)
class TimedWindow:
    """Inclusive chronological window bound to an evaluation role."""

    role: EvaluationWindow
    start_ts: str
    end_ts: str
    sealed: bool = False

    def contains(self, ts: str) -> bool:
        return compare_ts(self.start_ts, ts) <= 0 and compare_ts(ts, self.end_ts) <= 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "sealed": self.sealed,
        }


@dataclass
class EpistemicFirewall:
    """Authoritative as-of boundary for one historical / paper run.

    Agents, Brain, Memory, StrategyMemory, news and market views must consult
    this firewall rather than reading raw unrestricted stores.
    """

    as_of: str
    window: EvaluationWindow = EvaluationWindow.RESEARCH
    sealed_windows: list[TimedWindow] = field(default_factory=list)
    strategy_version: int | None = None
    run_id: str | None = None
    violations: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "window": self.window.value,
            "strategy_version": self.strategy_version,
            "run_id": self.run_id,
            "sealed_windows": [w.public_dict() for w in self.sealed_windows],
            "violations": self.violations,
            "truth": {
                "boundary": "available_at <= as_of",
                "event_time_alone_insufficient": True,
            },
        }

    def advance_as_of(self, ts: str) -> None:
        """Move the clock forward only (never backward)."""
        if compare_ts(ts, self.as_of) < 0:
            self.violations += 1
            raise CausalityViolation(
                f"Epistemic clock cannot move backward: {ts} < as_of {self.as_of}"
            )
        self.as_of = ts

    def assert_available(self, available_at: str | datetime | None, *, label: str = "record") -> None:
        if available_at is None:
            # Untimestamped time-sensitive records are refused in historical windows.
            if self.window in {
                EvaluationWindow.RESEARCH,
                EvaluationWindow.VALIDATION,
                EvaluationWindow.SEALED_TEST,
            }:
                self.violations += 1
                raise CausalityViolation(
                    f"{label} missing available_at under historical window {self.window.value}"
                )
            return
        if not is_available(available_at=available_at, as_of=self.as_of):
            self.violations += 1
            raise CausalityViolation(
                f"Look-ahead refused: {label} available_at={available_at} > as_of={self.as_of}"
            )

    def filter_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        label: str = "record",
        drop_missing: bool = True,
    ) -> list[dict[str, Any]]:
        """Return only records whose available_at <= as_of."""
        kept: list[dict[str, Any]] = []
        for raw in records:
            item = dict(raw)
            stamp = resolve_available_at(item)
            if stamp is None:
                if drop_missing:
                    continue
                self.assert_available(None, label=label)
                kept.append(item)
                continue
            if is_available(available_at=stamp, as_of=self.as_of):
                kept.append(item)
        return kept

    def assert_not_in_sealed_holdout(self, ts: str, *, purpose: str = "strategy_design") -> None:
        """Refuse sealed-holdout timestamps during research/design for this version."""
        if self.window == EvaluationWindow.SEALED_TEST:
            return  # Evaluator phase may read sealed window.
        for window in self.sealed_windows:
            if not window.sealed:
                continue
            if window.contains(ts):
                self.violations += 1
                raise CausalityViolation(
                    f"Sealed holdout refused during {purpose}: ts={ts} in "
                    f"{window.start_ts}..{window.end_ts}"
                )

    def assert_dataset_readable(
        self,
        *,
        dataset_sealed: bool,
        dataset_role: EvaluationWindow | str | None = None,
        purpose: str = "read",
    ) -> None:
        """Sealed test datasets are invisible during strategy creation/research."""
        role = dataset_role
        if isinstance(role, str):
            role = EvaluationWindow(role)
        if not dataset_sealed:
            return
        if role == EvaluationWindow.SEALED_TEST and self.window != EvaluationWindow.SEALED_TEST:
            self.violations += 1
            raise CausalityViolation(
                f"Sealed test dataset refused during window={self.window.value} purpose={purpose}"
            )


def assert_no_future_ts(timestamps: Sequence[str], clock_ts: str) -> None:
    """Fail if any timestamp is strictly after the clock (datetime-aware)."""
    for ts in timestamps:
        if compare_ts(ts, clock_ts) > 0:
            raise CausalityViolation(f"Event {ts} is after clock {clock_ts}")
