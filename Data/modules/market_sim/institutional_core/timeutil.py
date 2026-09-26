"""Canonical timezone-aware temporal semantics for institutional point-in-time logic.

Business ordering MUST use parsed datetime objects — never lexicographic string compare.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

UTC = timezone.utc


def parse_ts(value: Any) -> datetime:
    """Parse ISO-8601 / epoch / datetime into timezone-aware UTC datetime.

    Accepts:
      - datetime (naive treated as UTC)
      - ISO strings with Z / offsets
      - date-only (midnight UTC)
      - int/float unix seconds
    """
    if value is None or value == "":
        raise ValueError("empty timestamp")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # date-only
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        text = text + "T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_canonical(value: Any) -> str:
    """Persist timestamps as UTC ISO-8601 with explicit offset (+00:00)."""
    return parse_ts(value).isoformat(timespec="microseconds")


def compare_ts(a: Any, b: Any) -> int:
    """Return -1/0/1 for a<b / a==b / a>b using instant equality."""
    da, db = parse_ts(a), parse_ts(b)
    if da < db:
        return -1
    if da > db:
        return 1
    return 0


def ts_le(a: Any, b: Any) -> bool:
    return compare_ts(a, b) <= 0


def ts_lt(a: Any, b: Any) -> bool:
    return compare_ts(a, b) < 0


def ts_ge(a: Any, b: Any) -> bool:
    return compare_ts(a, b) >= 0


def ts_gt(a: Any, b: Any) -> bool:
    return compare_ts(a, b) > 0


def ts_eq(a: Any, b: Any) -> bool:
    return compare_ts(a, b) == 0


def window_contains(*, valid_from: Any, valid_to: Any | None, as_of: Any) -> bool:
    """Inclusive start, exclusive end temporal window."""
    if ts_lt(as_of, valid_from):
        return False
    if valid_to is not None and str(valid_to) and not ts_lt(as_of, valid_to):
        return False
    return True


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_canonical() -> str:
    return to_canonical(now_utc())


def in_zone(value: Any, zone: str) -> datetime:
    return parse_ts(value).astimezone(ZoneInfo(zone))


def is_dst_boundary(zone: str, local_date: str) -> dict[str, Any]:
    """Probe whether a local calendar day has a DST transition (offset change)."""
    z = ZoneInfo(zone)
    day = datetime.fromisoformat(local_date).date()
    samples = []
    for hour in range(0, 24):
        naive = datetime(day.year, day.month, day.day, hour, 0, 0)
        aware = naive.replace(tzinfo=z)
        samples.append(aware.utcoffset() or timedelta(0))
    offsets = {s for s in samples}
    return {
        "zone": zone,
        "localDate": local_date,
        "hasDstTransition": len(offsets) > 1,
        "offsetsSeconds": sorted({int(o.total_seconds()) for o in offsets}),
    }
