"""Calendar / session fail-closed tests (Wave 2)."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from Data.modules.market_sim.instruments import InstrumentFamily, InstrumentSpec, equity_session_is_open
from Data.modules.market_sim.universe import PointInTimeUniverse, SessionCalendarDay


class CalendarFailClosedExtendedTests(unittest.TestCase):
    def test_unknown_calendar_fails_closed(self) -> None:
        spec = InstrumentSpec(
            instrument_id="eq:AAPL",
            symbol="AAPL",
            family=InstrumentFamily.EQUITY,
            venue="XNAS",
            quote_currency="USD",
        )
        out = equity_session_is_open(spec, "2024-06-03", universe=None)
        self.assertFalse(out["isOpen"])
        self.assertEqual(out["sessionState"], "UNKNOWN")
        self.assertTrue(out["truth"]["fail_closed_on_unknown_calendar"])

    def test_half_day(self) -> None:
        uni = PointInTimeUniverse(
            calendar=[
                SessionCalendarDay(
                    "2024-07-03",
                    "half_day",
                    open_ts="2024-07-03T13:30:00Z",
                    close_ts="2024-07-03T17:00:00Z",
                    exchange="XNAS",
                    timezone="America/New_York",
                )
            ]
        )
        self.assertEqual(uni.trading_day_state("2024-07-03", exchange="XNAS"), "HALF_DAY")
        self.assertTrue(uni.is_trading_day("2024-07-03", exchange="XNAS"))

    def test_dst(self) -> None:
        # US equities spring-forward: 2024-03-10 America/New_York — wall clock jumps.
        tz = ZoneInfo("America/New_York")
        before = datetime(2024, 3, 10, 1, 30, tzinfo=tz)
        after = datetime(2024, 3, 10, 3, 30, tzinfo=tz)
        # Ambiguous/nonexistent local times must not silently become naive UTC.
        self.assertEqual(before.utcoffset().total_seconds(), -5 * 3600)
        self.assertEqual(after.utcoffset().total_seconds(), -4 * 3600)
        uni = PointInTimeUniverse(
            calendar=[
                SessionCalendarDay(
                    "2024-03-11",
                    "open",
                    open_ts="2024-03-11T13:30:00Z",
                    close_ts="2024-03-11T20:00:00Z",
                    exchange="XNAS",
                    timezone="America/New_York",
                )
            ]
        )
        # Date present after DST transition remains OPEN when declared.
        self.assertEqual(uni.trading_day_state("2024-03-11", exchange="XNAS"), "OPEN")
        # Missing date still UNKNOWN (fail-closed) — not weekday=open.
        self.assertEqual(uni.trading_day_state("2024-03-12", exchange="XNAS"), "UNKNOWN")

    def test_overnight_future_session(self) -> None:
        uni = PointInTimeUniverse(
            calendar=[
                SessionCalendarDay(
                    "2024-06-03",
                    "open",
                    open_ts="2024-06-02T22:00:00Z",
                    close_ts="2024-06-03T21:00:00Z",
                    exchange="CME",
                    timezone="America/Chicago",
                )
            ]
        )
        self.assertEqual(uni.trading_day_state("2024-06-03", exchange="CME"), "OPEN")
        day = uni.calendar[0]
        self.assertLess(day.open_ts, day.close_ts)
        # Overnight: open timestamp is previous calendar evening UTC.
        self.assertTrue(str(day.open_ts).startswith("2024-06-02"))

    def test_crypto_24_7(self) -> None:
        # Crypto has no exchange holiday calendar — session model is always-open
        # only when an explicit 24/7 calendar is configured, never by weekday guess.
        uni = PointInTimeUniverse(calendar=[])
        self.assertEqual(uni.trading_day_state("2024-06-01"), "UNKNOWN")
        # Explicit 24/7 venue calendar may mark every day open.
        crypto_cal = PointInTimeUniverse(
            calendar=[
                SessionCalendarDay(f"2024-06-0{d}", "open", exchange="BINANCE", timezone="UTC")
                for d in range(1, 8)
            ]
        )
        for d in range(1, 8):
            self.assertEqual(
                crypto_cal.trading_day_state(f"2024-06-0{d}", exchange="BINANCE"),
                "OPEN",
            )

    def test_fx_weekend(self) -> None:
        uni = PointInTimeUniverse(
            calendar=[
                SessionCalendarDay("2024-06-07", "closed", exchange="FX", timezone="UTC"),  # Friday ok
                SessionCalendarDay("2024-06-08", "closed", exchange="FX", timezone="UTC"),  # Saturday
                SessionCalendarDay("2024-06-09", "closed", exchange="FX", timezone="UTC"),  # Sunday
                SessionCalendarDay(
                    "2024-06-10",
                    "open",
                    open_ts="2024-06-10T00:00:00Z",
                    close_ts="2024-06-10T23:59:59Z",
                    exchange="FX",
                    timezone="UTC",
                ),
            ]
        )
        self.assertEqual(uni.trading_day_state("2024-06-08", exchange="FX"), "CLOSED")
        self.assertEqual(uni.trading_day_state("2024-06-09", exchange="FX"), "CLOSED")
        self.assertFalse(uni.is_trading_day("2024-06-08", exchange="FX"))
        self.assertTrue(uni.is_trading_day("2024-06-10", exchange="FX"))


if __name__ == "__main__":
    unittest.main()
