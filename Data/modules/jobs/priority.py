"""Latency classes and priority helpers for runnable job selection."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class LatencyClass(str, Enum):
    INTERACTIVE = "interactive"
    STANDARD = "standard"
    BACKGROUND = "background"


# Lower number = higher priority.
PRIORITY_INTERACTIVE = 10
PRIORITY_STANDARD = 50
PRIORITY_BACKGROUND = 100
PRIORITY_DEFAULT = PRIORITY_BACKGROUND

LATENCY_CLASS_PRIORITY: dict[str, int] = {
    LatencyClass.INTERACTIVE.value: PRIORITY_INTERACTIVE,
    LatencyClass.STANDARD.value: PRIORITY_STANDARD,
    LatencyClass.BACKGROUND.value: PRIORITY_BACKGROUND,
}


def priority_for_latency_class(latency_class: str | LatencyClass | None) -> int:
    if latency_class is None:
        return PRIORITY_DEFAULT
    key = latency_class.value if isinstance(latency_class, LatencyClass) else str(latency_class)
    return int(LATENCY_CLASS_PRIORITY.get(key, PRIORITY_DEFAULT))


def _parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def aged_priority(
    base_priority: int,
    *,
    created_at: str | datetime | None,
    now: datetime | None = None,
    aging_seconds: float = 60.0,
    max_boost: int = 50,
) -> float:
    """Return effective priority (lower = sooner). Aging boosts older jobs.

    Every ``aging_seconds`` of age reduces the effective priority by 1, up to
    ``max_boost``, so starved low-priority work eventually runs.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    created = _parse_ts(created_at)
    if created is None or aging_seconds <= 0:
        return float(base_priority)
    age = max(0.0, (current - created).total_seconds())
    boost = min(int(max_boost), int(age // float(aging_seconds)))
    return float(base_priority) - float(boost)
