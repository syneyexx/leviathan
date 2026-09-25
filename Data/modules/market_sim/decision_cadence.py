"""Explicit decision cadence + asynchronous DecisionRecord eligibility (P3A).

Cadence is an explicit recorded parameter — never a silent multi-agent default.
Async DecisionRecords become eligible when simulation as_of >= record.as_of;
they never rewind the clock and never peek future bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

CADENCE_EVERY_N_BARS = "every_n_bars"
CADENCE_DAILY_CLOSE = "daily_close"
CADENCE_HOURLY = "hourly"
CADENCE_EVENT_DRIVEN = "event_driven"
CADENCE_OFF = "off"

SUPPORTED_CADENCES = frozenset(
    {
        CADENCE_EVERY_N_BARS,
        CADENCE_DAILY_CLOSE,
        CADENCE_HOURLY,
        CADENCE_EVENT_DRIVEN,
        CADENCE_OFF,
    }
)


def normalize_cadence(raw: str | None, *, default: str = CADENCE_EVERY_N_BARS) -> str:
    text = str(raw or default).strip().lower()
    if text not in SUPPORTED_CADENCES:
        raise ValueError(f"Unsupported decision_cadence: {raw!r}")
    return text


def should_decide_on_bar(
    *,
    cadence: str,
    bar_index: int,
    bar_ts: str,
    every_n: int = 1,
    previous_decision_ts: str | None = None,
    event_triggered: bool = False,
) -> bool:
    """Deterministic cadence gate for historical / paper bars."""
    mode = normalize_cadence(cadence)
    if mode == CADENCE_OFF:
        return False
    if mode == CADENCE_EVENT_DRIVEN:
        return bool(event_triggered)
    if mode == CADENCE_EVERY_N_BARS:
        n = max(1, int(every_n))
        return bar_index > 0 and (bar_index % n == 0)
    if mode == CADENCE_HOURLY:
        return _hour_boundary(bar_ts, previous_decision_ts)
    if mode == CADENCE_DAILY_CLOSE:
        return _day_boundary(bar_ts, previous_decision_ts)
    return False


def _parse_ts(ts: str) -> datetime | None:
    text = str(ts or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _hour_boundary(bar_ts: str, previous: str | None) -> bool:
    cur = _parse_ts(bar_ts)
    if cur is None:
        return False
    prev = _parse_ts(previous) if previous else None
    if prev is None:
        return True
    return (cur.year, cur.month, cur.day, cur.hour) != (prev.year, prev.month, prev.day, prev.hour)


def _day_boundary(bar_ts: str, previous: str | None) -> bool:
    cur = _parse_ts(bar_ts)
    if cur is None:
        return False
    prev = _parse_ts(previous) if previous else None
    if prev is None:
        return True
    return (cur.year, cur.month, cur.day) != (prev.year, prev.month, prev.day)


@dataclass
class AsyncDecisionRecord:
    """Pending DecisionRecord payload waiting for causal eligibility."""

    decision_id: str
    as_of: str
    payload: dict[str, Any]
    stage: str = "order_intent"
    parent_decision_id: str | None = None
    applied: bool = False
    created_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "as_of": self.as_of,
            "stage": self.stage,
            "payload": dict(self.payload),
            "parent_decision_id": self.parent_decision_id,
            "applied": self.applied,
            "created_at": self.created_at,
        }


@dataclass
class AsyncDecisionQueue:
    """Append-only pending decisions; apply only when as_of <= clock."""

    _pending: list[AsyncDecisionRecord] = field(default_factory=list)
    _applied: list[AsyncDecisionRecord] = field(default_factory=list)

    def enqueue(self, record: AsyncDecisionRecord) -> AsyncDecisionRecord:
        self._pending.append(record)
        return record

    def eligible(self, *, as_of: str) -> list[AsyncDecisionRecord]:
        return [r for r in self._pending if not r.applied and r.as_of <= as_of]

    def apply_eligible(self, *, as_of: str) -> list[AsyncDecisionRecord]:
        """Mark eligible records applied (never rewind; never future peek)."""
        ready = self.eligible(as_of=as_of)
        for rec in ready:
            rec.applied = True
            self._applied.append(rec)
        self._pending = [r for r in self._pending if not r.applied]
        return ready

    def reject_future_peek(self, *, as_of: str, records: Iterable[AsyncDecisionRecord]) -> list[AsyncDecisionRecord]:
        """Filter out records that would require future information."""
        return [r for r in records if r.as_of <= as_of]

    def public_dict(self) -> dict[str, Any]:
        return {
            "pending": [r.public_dict() for r in self._pending],
            "applied": [r.public_dict() for r in self._applied],
            "truth": {
                "append_only": True,
                "causal_as_of": True,
                "no_rewind": True,
            },
        }
