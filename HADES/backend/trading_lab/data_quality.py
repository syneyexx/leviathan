"""Deterministic dataset validation.

This is code, not a prompt. The Data Steward agent reads these reports; it does not
produce them. Every check either accepts a row, rejects a row, or raises a blocking issue.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Sequence

from trading_lab.calendars import get_calendar, timeframe_seconds
from trading_lab.contracts import (
    DataQualityIssue,
    DataQualityReport,
    InstrumentSpec,
    MarketEvent,
    utc_iso,
)

_EPOCH_MIN = 10_000_000  # ~1970-04-26; anything smaller is not a plausible epoch second
_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")

_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
    "%Y%m%d",
    "%Y%m%d%H%M%S",
)


class TimestampError(ValueError):
    """Raised when a timestamp cannot be normalised without guessing."""


def normalise_timestamp(value: Any, *, assume_timezone: str = "UTC") -> datetime:
    """Normalise a raw timestamp to an aware UTC datetime.

    Accepts ISO-8601 (with or without offset, ``Z`` suffix allowed), epoch seconds,
    epoch milliseconds, and a bounded set of unambiguous calendar formats. Anything else
    raises rather than silently guessing, because a wrong timestamp silently corrupts the
    whole point-in-time model.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise TimestampError("empty_timestamp")
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, (int, float)):
        stamp = _from_epoch(float(value))
    else:
        text = str(value).strip()
        if _NUMERIC.match(text):
            stamp = _from_epoch(float(text))
        else:
            candidate = text.replace("Z", "+00:00").replace("z", "+00:00")
            if candidate.count(" ") == 1 and "T" not in candidate and len(candidate.split(" ")[0]) == 10:
                candidate = candidate.replace(" ", "T", 1)
            try:
                stamp = datetime.fromisoformat(candidate)
            except ValueError:
                stamp = _from_formats(text)
    if stamp.tzinfo is None:
        if assume_timezone.upper() != "UTC":
            try:
                from zoneinfo import ZoneInfo

                stamp = stamp.replace(tzinfo=ZoneInfo(assume_timezone))
            except Exception as exc:  # pragma: no cover - depends on tzdata presence
                raise TimestampError(f"unknown_timezone:{assume_timezone}") from exc
        else:
            stamp = stamp.replace(tzinfo=UTC)
    normalised = stamp.astimezone(UTC)
    if not 1900 <= normalised.year <= 2200:
        raise TimestampError(f"implausible_timestamp_year:{normalised.year}")
    return normalised


def _from_epoch(raw: float) -> datetime:
    if not math.isfinite(raw):
        raise TimestampError("non_finite_epoch")
    magnitude = abs(raw)
    if magnitude >= 1e17:
        seconds = raw / 1e9  # nanoseconds
    elif magnitude >= 1e14:
        seconds = raw / 1e6  # microseconds
    elif magnitude >= 1e11:
        seconds = raw / 1e3  # milliseconds
    elif magnitude >= _EPOCH_MIN:
        seconds = raw
    else:
        raise TimestampError(f"ambiguous_numeric_timestamp:{raw}")
    return datetime.fromtimestamp(seconds, tz=UTC)


def _from_formats(text: str) -> datetime:
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise TimestampError(f"unparsable_timestamp:{text}")


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non_finite_value")
    return number


class BarValidator:
    """Validate raw OHLCV rows into ``MarketEvent`` objects plus a quality report."""

    def __init__(
        self,
        spec: InstrumentSpec,
        timeframe: str,
        *,
        source: str = "import",
        availability_delay_seconds: int = 0,
        assume_timezone: str = "UTC",
        stale_run_threshold: int = 5,
        outlier_sigma: float = 12.0,
    ) -> None:
        self.spec = spec
        self.timeframe = timeframe
        self.source = source
        self.availability_delay_seconds = max(0, int(availability_delay_seconds))
        self.assume_timezone = assume_timezone
        self.stale_run_threshold = max(2, int(stale_run_threshold))
        self.outlier_sigma = float(outlier_sigma)
        self._step = timeframe_seconds(timeframe)
        self._calendar = get_calendar(spec.calendar)

    def validate(self, rows: Iterable[dict[str, Any]]) -> tuple[list[MarketEvent], DataQualityReport]:
        counters: dict[str, int] = {}
        samples: dict[str, list[str]] = {}
        accepted: dict[datetime, MarketEvent] = {}
        rows_in = 0
        previous_stamp: datetime | None = None
        out_of_order = 0
        duplicates = 0
        ingested_at = utc_iso(datetime.now(UTC))

        def fail(code: str, detail: str) -> None:
            counters[code] = counters.get(code, 0) + 1
            bucket = samples.setdefault(code, [])
            if len(bucket) < 5:
                bucket.append(detail)

        for row in rows:
            rows_in += 1
            try:
                stamp = normalise_timestamp(
                    _first(row, ("ts", "timestamp", "time", "datetime", "date", "event_time", "open_time")),
                    assume_timezone=self.assume_timezone,
                )
            except TimestampError as exc:
                fail("invalid_timestamp", str(exc))
                continue
            try:
                open_px = _finite(_first(row, ("open", "o")))
                high_px = _finite(_first(row, ("high", "h")))
                low_px = _finite(_first(row, ("low", "l")))
                close_px = _finite(_first(row, ("close", "c", "price")))
            except (TypeError, ValueError, KeyError) as exc:
                fail("non_finite_or_missing_ohlc", f"{stamp.isoformat()}: {exc}")
                continue
            volume_raw = _first(row, ("volume", "v", "vol"), required=False)
            try:
                volume = _finite(volume_raw) if volume_raw not in (None, "") else 0.0
            except ValueError:
                fail("non_finite_volume", stamp.isoformat())
                continue
            if volume < 0:
                fail("negative_volume", stamp.isoformat())
                continue
            try:
                for price in (open_px, high_px, low_px, close_px):
                    self.spec.validate_price(price)
            except ValueError as exc:
                fail("price_sign_violation", f"{stamp.isoformat()}: {exc}")
                continue
            if high_px < max(open_px, close_px) - 1e-12 or low_px > min(open_px, close_px) + 1e-12 or high_px < low_px:
                fail(
                    "ohlc_inconsistent",
                    f"{stamp.isoformat()}: o={open_px} h={high_px} l={low_px} c={close_px}",
                )
                continue
            if previous_stamp is not None and stamp < previous_stamp:
                out_of_order += 1
            previous_stamp = stamp
            if stamp in accepted:
                duplicates += 1
                existing = accepted[stamp]
                if (existing.open, existing.high, existing.low, existing.close) != (open_px, high_px, low_px, close_px):
                    fail("conflicting_duplicate_timestamp", stamp.isoformat())
                    continue
                fail("duplicate_timestamp", stamp.isoformat())
                continue
            bar_close = stamp + timedelta(seconds=self._step)
            available_at = bar_close + timedelta(seconds=self.availability_delay_seconds)
            accepted[stamp] = MarketEvent(
                instrument_id=self.spec.instrument_id,
                timeframe=self.timeframe,
                event_time=utc_iso(stamp),
                available_at=utc_iso(available_at),
                ingested_at=ingested_at,
                kind="bar",
                open=open_px,
                high=high_px,
                low=low_px,
                close=close_px,
                volume=volume,
                bid=_optional_float(_first(row, ("bid",), required=False)),
                ask=_optional_float(_first(row, ("ask",), required=False)),
                mark_price=_optional_float(_first(row, ("mark", "mark_price"), required=False)),
                index_price=_optional_float(_first(row, ("index", "index_price"), required=False)),
                funding_rate=_optional_float(_first(row, ("funding", "funding_rate"), required=False)),
                open_interest=_optional_float(_first(row, ("open_interest", "oi"), required=False)),
                revision=int(_first(row, ("revision",), required=False) or 1),
                source=str(_first(row, ("source",), required=False) or self.source),
            )

        events = [accepted[key] for key in sorted(accepted)]
        report = self._report(
            rows_in=rows_in,
            events=events,
            counters=counters,
            samples=samples,
            duplicates=duplicates,
            out_of_order=out_of_order,
        )
        return events, report

    def _report(
        self,
        *,
        rows_in: int,
        events: Sequence[MarketEvent],
        counters: dict[str, int],
        samples: dict[str, list[str]],
        duplicates: int,
        out_of_order: int,
    ) -> DataQualityReport:
        issues: list[DataQualityIssue] = []
        severity_map = {
            "invalid_timestamp": "error",
            "non_finite_or_missing_ohlc": "error",
            "non_finite_volume": "error",
            "negative_volume": "error",
            "price_sign_violation": "error",
            "ohlc_inconsistent": "error",
            "conflicting_duplicate_timestamp": "error",
            "duplicate_timestamp": "warning",
        }
        for code, count in sorted(counters.items()):
            issues.append(
                DataQualityIssue(
                    code=code,
                    severity=severity_map.get(code, "warning"),
                    count=count,
                    detail=_ISSUE_DETAIL.get(code, code),
                    sample=samples.get(code, []),
                )
            )
        if out_of_order:
            issues.append(
                DataQualityIssue(
                    code="out_of_order_rows",
                    severity="warning",
                    count=out_of_order,
                    detail="Source rows were not chronological; they were reordered before storage.",
                )
            )

        expected = missing = None
        gap_ratio = None
        if len(events) >= 2:
            first = datetime.fromisoformat(events[0].event_time)
            last = datetime.fromisoformat(events[-1].event_time)
            expected = self._expected_bars(first, last)
            missing = max(0, expected - len(events))
            gap_ratio = (missing / expected) if expected else 0.0
            if gap_ratio and gap_ratio > 0.02:
                issues.append(
                    DataQualityIssue(
                        code="coverage_gaps",
                        severity="warning" if gap_ratio < 0.25 else "error",
                        count=missing,
                        detail=(
                            f"{missing} of {expected} expected {self.timeframe} observations are missing "
                            f"on calendar {self._calendar.calendar_id} ({gap_ratio:.1%})."
                        ),
                    )
                )

        stale_runs = self._stale_runs(events)
        if stale_runs:
            issues.append(
                DataQualityIssue(
                    code="stale_quotes",
                    severity="warning",
                    count=stale_runs,
                    detail=(
                        f"{stale_runs} run(s) of >= {self.stale_run_threshold} identical closes with zero range; "
                        "these look like carried-forward quotes rather than trading activity."
                    ),
                )
            )

        outliers = self._outliers(events)
        if outliers:
            issues.append(
                DataQualityIssue(
                    code="return_outliers",
                    severity="warning",
                    count=len(outliers),
                    detail=(
                        f"{len(outliers)} observation(s) move more than {self.outlier_sigma:g} robust sigma; "
                        "verify against the source before using them as tradable history."
                    ),
                    sample=outliers[:5],
                )
            )

        return DataQualityReport(
            rows_in=rows_in,
            rows_accepted=len(events),
            rows_rejected=max(0, rows_in - len(events)),
            first_event_time=events[0].event_time if events else None,
            last_event_time=events[-1].event_time if events else None,
            expected_bars=expected,
            missing_bars=missing,
            gap_ratio=gap_ratio,
            stale_runs=stale_runs,
            duplicate_timestamps=duplicates,
            out_of_order=out_of_order,
            issues=issues,
        )

    def _expected_bars(self, first: datetime, last: datetime) -> int:
        if self._step <= 0:
            return 0
        if self._calendar.continuous:
            return int((last - first).total_seconds() // self._step) + 1
        # Count only slots the calendar is open for; walk in steps, bounded to keep this cheap.
        total_slots = int((last - first).total_seconds() // self._step) + 1
        if total_slots > 2_000_000:
            open_fraction = (self._calendar.session_hours / 24.0) * (len(self._calendar.weekdays) / 7.0)
            return max(1, int(total_slots * open_fraction))
        count = 0
        cursor = first
        step = timedelta(seconds=self._step)
        while cursor <= last:
            if self._calendar.is_open(cursor):
                count += 1
            cursor += step
        return max(count, 1)

    def _stale_runs(self, events: Sequence[MarketEvent]) -> int:
        runs = 0
        length = 1
        for index in range(1, len(events)):
            previous, current = events[index - 1], events[index]
            identical = (
                current.close == previous.close
                and current.open == current.close
                and current.high == current.low
            )
            if identical:
                length += 1
                if length == self.stale_run_threshold:
                    runs += 1
            else:
                length = 1
        return runs

    def _outliers(self, events: Sequence[MarketEvent]) -> list[str]:
        if len(events) < 30:
            return []
        returns: list[tuple[int, float]] = []
        for index in range(1, len(events)):
            previous = events[index - 1].close or 0.0
            current = events[index].close or 0.0
            if previous == 0:
                continue
            returns.append((index, (current - previous) / abs(previous)))
        if len(returns) < 30:
            return []
        values = sorted(value for _, value in returns)
        median = values[len(values) // 2]
        deviations = sorted(abs(value - median) for value in values)
        mad = deviations[len(deviations) // 2]
        if mad <= 0:
            return []
        scale = mad * 1.4826
        flagged = [
            events[index].event_time
            for index, value in returns
            if abs(value - median) / scale > self.outlier_sigma
        ]
        return flagged


_ISSUE_DETAIL = {
    "invalid_timestamp": "Timestamp could not be normalised to UTC without guessing.",
    "non_finite_or_missing_ohlc": "Row contained a missing, NaN or Infinity OHLC value.",
    "non_finite_volume": "Row contained a non-finite volume.",
    "negative_volume": "Row contained a negative volume.",
    "price_sign_violation": "Price violated the instrument's own sign rule (not a universal positive-price rule).",
    "ohlc_inconsistent": "high < max(open, close), low > min(open, close) or high < low.",
    "duplicate_timestamp": "Identical duplicate row dropped; the first occurrence was kept.",
    "conflicting_duplicate_timestamp": "Two rows share a timestamp with different values; both were rejected.",
}


def _first(row: dict[str, Any], names: tuple[str, ...], *, required: bool = True) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items() if key is not None}
    for name in names:
        if name in lowered and lowered[name] not in (None, ""):
            return lowered[name]
    if required:
        raise KeyError(f"missing_column:{names[0]}")
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def summarise_report(report: DataQualityReport) -> str:
    parts = [f"{report.rows_accepted}/{report.rows_in} rows accepted"]
    if report.rows_rejected:
        parts.append(f"{report.rows_rejected} rejected")
    if report.missing_bars:
        parts.append(f"{report.missing_bars} missing observations")
    if report.duplicate_timestamps:
        parts.append(f"{report.duplicate_timestamps} duplicate timestamps")
    if report.stale_runs:
        parts.append(f"{report.stale_runs} stale runs")
    errors = [issue.code for issue in report.issues if issue.severity == "error"]
    if errors:
        parts.append("blocking: " + ", ".join(sorted(set(errors))))
    return "; ".join(parts)


__all__ = ["BarValidator", "TimestampError", "normalise_timestamp", "summarise_report"]
