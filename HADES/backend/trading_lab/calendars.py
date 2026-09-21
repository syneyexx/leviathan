"""Trading calendars.

Used for two different things that are often conflated:

1. whether a venue is open at a given instant (session gating, DAY order expiry);
2. how many observations of a given timeframe fit in a year (correct annualisation).

The calendars here are deliberately simple and explicit. They model regular weekly
sessions, not exchange holiday tables — HADES ships no holiday dataset, and inventing one
would be worse than saying so. ``holiday_coverage`` reports that honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

TIMEFRAME_SECONDS: dict[str, int] = {
    "1s": 1,
    "5s": 5,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "1w": 604800,
    "1M": 2592000,
}


def timeframe_seconds(timeframe: str) -> int:
    key = (timeframe or "").strip()
    if key in TIMEFRAME_SECONDS:
        return TIMEFRAME_SECONDS[key]
    raise ValueError(f"unknown_timeframe:{timeframe}")


@dataclass(frozen=True)
class TradingCalendar:
    calendar_id: str
    name: str
    weekdays: tuple[int, ...]
    session_start: time
    session_end: time
    session_hours: float
    sessions_per_year: float
    continuous: bool = False
    holiday_coverage: str = "none_modelled"
    notes: str = ""
    breaks: tuple[tuple[time, time], ...] = field(default=())

    def is_open(self, moment: datetime) -> bool:
        stamp = moment.astimezone(UTC)
        if stamp.weekday() not in self.weekdays:
            return False
        if self.continuous:
            return True
        clock = stamp.timetz().replace(tzinfo=None)
        if self.session_start <= self.session_end:
            inside = self.session_start <= clock < self.session_end
        else:  # session wraps midnight (FX week)
            inside = clock >= self.session_start or clock < self.session_end
        if not inside:
            return False
        return not any(start <= clock < end for start, end in self.breaks)

    def session_end_utc(self, moment: datetime) -> datetime:
        """End of the session containing (or following) ``moment``; used for DAY expiry."""
        stamp = moment.astimezone(UTC)
        if self.continuous:
            return stamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        candidate = datetime.combine(stamp.date(), self.session_end, tzinfo=UTC)
        if self.session_start > self.session_end:
            candidate = candidate + timedelta(days=1)
        if candidate <= stamp:
            candidate = candidate + timedelta(days=1)
        return candidate

    def expected_periods(self, start: datetime, end: datetime, step_seconds: int) -> int:
        """How many observations of ``step_seconds`` this calendar expects in ``[start, end)``.

        Walking the grid keeps weekend and session gaps out of the "missing data" count, which
        is what makes a gap report on an equity series meaningful instead of alarming.
        """
        if step_seconds <= 0 or end <= start:
            return 0
        if self.continuous:
            return int((end - start).total_seconds() // step_seconds)
        if step_seconds >= 86400:
            days = 0
            cursor = start.astimezone(UTC)
            limit = end.astimezone(UTC)
            while cursor < limit and days < 200000:
                if cursor.weekday() in self.weekdays:
                    days += 1
                cursor = cursor + timedelta(days=1)
            return int(days // max(1, step_seconds // 86400))
        count = 0
        cursor = start.astimezone(UTC)
        limit = end.astimezone(UTC)
        guard = 0
        while cursor < limit and guard < 2_000_000:
            if self.is_open(cursor):
                count += 1
            cursor = cursor + timedelta(seconds=step_seconds)
            guard += 1
        return count

    def periods_per_year(self, timeframe: str) -> float:
        """Observations of ``timeframe`` per year on this calendar."""
        seconds = timeframe_seconds(timeframe)
        if seconds >= 86400:
            # Daily and coarser: count sessions, not wall-clock seconds.
            return max(1.0, self.sessions_per_year * (86400.0 / seconds))
        per_session = (self.session_hours * 3600.0) / seconds
        return max(1.0, per_session * self.sessions_per_year)


CRYPTO_24X7 = TradingCalendar(
    calendar_id="24x7",
    name="Continuous (crypto)",
    weekdays=(0, 1, 2, 3, 4, 5, 6),
    session_start=time(0, 0),
    session_end=time(0, 0),
    session_hours=24.0,
    sessions_per_year=365.0,
    continuous=True,
    holiday_coverage="not_applicable",
    notes="Crypto venues trade continuously; maintenance windows are not modelled.",
)

US_EQUITY_RTH = TradingCalendar(
    calendar_id="us_equity_rth",
    name="US equity regular hours",
    weekdays=(0, 1, 2, 3, 4),
    session_start=time(13, 30),
    session_end=time(20, 0),
    session_hours=6.5,
    sessions_per_year=252.0,
    holiday_coverage="none_modelled",
    notes="13:30-20:00 UTC approximates 09:30-16:00 US/Eastern; DST shifts and market holidays are not modelled.",
)

FX_5X24 = TradingCalendar(
    calendar_id="fx_5x24",
    name="FX rolling week",
    weekdays=(0, 1, 2, 3, 4, 6),
    session_start=time(21, 0),
    session_end=time(21, 0),
    session_hours=24.0,
    sessions_per_year=260.0,
    continuous=False,
    holiday_coverage="none_modelled",
    notes="Sunday 21:00 UTC open through Friday 21:00 UTC close; bank holidays are not modelled.",
)

CME_NEAR_24 = TradingCalendar(
    calendar_id="cme_near_24",
    name="CME near-continuous",
    weekdays=(0, 1, 2, 3, 4, 6),
    session_start=time(23, 0),
    session_end=time(22, 0),
    session_hours=23.0,
    sessions_per_year=252.0,
    holiday_coverage="none_modelled",
    breaks=((time(22, 0), time(23, 0)),),
    notes="Sunday 23:00 UTC open, daily 22:00-23:00 UTC maintenance break; holidays are not modelled.",
)

BOND_OTC = TradingCalendar(
    calendar_id="bond_otc",
    name="OTC bond business day",
    weekdays=(0, 1, 2, 3, 4),
    session_start=time(7, 0),
    session_end=time(17, 0),
    session_hours=10.0,
    sessions_per_year=252.0,
    holiday_coverage="none_modelled",
    notes="Indicative business-day window; bond markets are dealer-quoted, not exchange-continuous.",
)

CALENDARS: dict[str, TradingCalendar] = {
    calendar.calendar_id: calendar
    for calendar in (CRYPTO_24X7, US_EQUITY_RTH, FX_5X24, CME_NEAR_24, BOND_OTC)
}


def get_calendar(calendar_id: str | None) -> TradingCalendar:
    return CALENDARS.get((calendar_id or "24x7").strip(), CRYPTO_24X7)


def periods_per_year(timeframe: str, calendar_id: str | None = None) -> float:
    """Timeframe-aware, calendar-aware annualisation factor.

    This replaces the fixed ``sqrt(24 * 365)`` proxy in the legacy bot: a daily equity bar
    annualises with 252, a 1h crypto bar with 8760.
    """
    return get_calendar(calendar_id).periods_per_year(timeframe)


__all__ = [
    "BOND_OTC",
    "CALENDARS",
    "CME_NEAR_24",
    "CRYPTO_24X7",
    "FX_5X24",
    "TIMEFRAME_SECONDS",
    "TradingCalendar",
    "US_EQUITY_RTH",
    "get_calendar",
    "periods_per_year",
    "timeframe_seconds",
]
