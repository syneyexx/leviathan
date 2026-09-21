"""Market data validation: timestamps, OHLC consistency, gaps and availability.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.contracts import InstrumentSpec
from trading_lab.data_quality import BarValidator, TimestampError, normalise_timestamp

SPOT = InstrumentSpec(
    instrument_id="crypto_spot:test:BTCUSDT",
    family="crypto_spot",
    venue="test",
    symbol="BTCUSDT",
    base_currency="BTC",
    quote_currency="USDT",
    tick_size=Decimal("0.01"),
    lot_size=Decimal("0.001"),
)


def row(ts: str, *, open_: float = 100, high: float = 101, low: float = 99, close: float = 100, volume: float = 5) -> dict:
    return {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


class TimestampTest(unittest.TestCase):
    def test_naive_timestamps_are_read_in_the_declared_timezone(self) -> None:
        stamp = normalise_timestamp("2020-01-01 00:00:00", assume_timezone="UTC")
        self.assertEqual(stamp.isoformat(), "2020-01-01T00:00:00+00:00")

    def test_epoch_seconds_and_milliseconds_both_work(self) -> None:
        seconds = normalise_timestamp(1577836800)
        millis = normalise_timestamp(1577836800000)
        self.assertEqual(seconds, millis)

    def test_garbage_is_rejected_not_guessed(self) -> None:
        with self.assertRaises(TimestampError):
            normalise_timestamp("not a date")


class BarValidatorTest(unittest.TestCase):
    def validator(self, **kwargs) -> BarValidator:
        return BarValidator(SPOT, "1h", **kwargs)

    def test_clean_rows_are_accepted_and_ordered(self) -> None:
        events, report = self.validator().validate(
            [row("2020-01-01T02:00:00+00:00"), row("2020-01-01T00:00:00+00:00"), row("2020-01-01T01:00:00+00:00")]
        )
        self.assertEqual(report.rows_accepted, 3)
        self.assertEqual([event.event_time for event in events], sorted(event.event_time for event in events))
        self.assertEqual(report.out_of_order, 1, "the input order is reported, the output is sorted")

    def test_availability_is_the_bar_close_plus_the_declared_delay(self) -> None:
        events, _ = self.validator(availability_delay_seconds=60).validate([row("2020-01-01T00:00:00+00:00")])
        self.assertEqual(events[0].event_time, "2020-01-01T00:00:00+00:00")
        self.assertEqual(events[0].available_at, "2020-01-01T01:01:00+00:00")

    def test_inconsistent_ohlc_is_rejected(self) -> None:
        _, report = self.validator().validate([row("2020-01-01T00:00:00+00:00", high=95)])
        self.assertEqual(report.rows_accepted, 0)
        self.assertEqual(report.rows_rejected, 1)
        self.assertTrue(any(issue.code == "ohlc_inconsistent" for issue in report.issues))

    def test_non_finite_values_are_rejected(self) -> None:
        _, report = self.validator().validate([{"ts": "2020-01-01T00:00:00+00:00", "open": "nan", "high": 1, "low": 1, "close": 1}])
        self.assertEqual(report.rows_accepted, 0)

    def test_negative_volume_is_rejected(self) -> None:
        _, report = self.validator().validate([row("2020-01-01T00:00:00+00:00", volume=-1)])
        self.assertEqual(report.rows_accepted, 0)
        self.assertTrue(any(issue.code == "negative_volume" for issue in report.issues))

    def test_identical_duplicates_collapse_and_conflicting_ones_are_flagged(self) -> None:
        _, identical = self.validator().validate(
            [row("2020-01-01T00:00:00+00:00"), row("2020-01-01T00:00:00+00:00")]
        )
        self.assertEqual(identical.rows_accepted, 1)
        self.assertEqual(identical.duplicate_timestamps, 1)

        _, conflicting = self.validator().validate(
            [row("2020-01-01T00:00:00+00:00"), row("2020-01-01T00:00:00+00:00", close=250, high=250)]
        )
        self.assertTrue(
            any(issue.code == "conflicting_duplicate_timestamp" for issue in conflicting.issues),
            "two different prices for the same minute is a source problem, not a rounding detail",
        )

    def test_missing_bars_are_counted_against_the_calendar(self) -> None:
        rows = [row(f"2020-01-01T{hour:02d}:00:00+00:00") for hour in range(0, 10) if hour != 5]
        _, report = self.validator().validate(rows)
        self.assertEqual(report.rows_accepted, 9)
        self.assertEqual(report.missing_bars, 1)
        self.assertIsNotNone(report.gap_ratio)

    def test_a_flat_run_is_reported_as_stale(self) -> None:
        rows = [
            row(f"2020-01-01T{hour:02d}:00:00+00:00", open_=100, high=100, low=100, close=100, volume=0)
            for hour in range(0, 8)
        ]
        _, report = self.validator(stale_run_threshold=3).validate(rows)
        self.assertGreater(report.stale_runs, 0)

    def test_empty_input_reports_instead_of_raising(self) -> None:
        events, report = self.validator().validate([])
        self.assertEqual(events, [])
        self.assertEqual(report.rows_in, 0)
        self.assertEqual(report.rows_accepted, 0)


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
