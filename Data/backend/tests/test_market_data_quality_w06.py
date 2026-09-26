"""WAVE 06 — market data quality and point-in-time data fabric."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.dataset_pipeline import analyze_bars, analyze_quote_snapshot
from Data.modules.market_sim.pit_fabric import (
    bars_to_pit_observations,
    build_revision_identity,
    filter_bars_as_of,
    filter_observations_as_of,
    quality_with_pit_labels,
    survivorship_membership_as_of,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import Bar
from Data.modules.market_sim.universe import (
    MembershipEvent,
    MembershipEventKind,
    PointInTimeUniverse,
)


def _bar(ts: str, o: float = 10, h: float = 11, l: float = 9, c: float = 10.5, v: float = 100) -> Bar:
    return Bar(ts, o, h, l, c, v)


class AnalyzeBarsQualityW06Tests(unittest.TestCase):
    def test_pass_clean_series(self) -> None:
        bars = [
            _bar("2024-01-01T00:00:00+00:00"),
            _bar("2024-01-01T01:00:00+00:00"),
            _bar("2024-01-01T02:00:00+00:00"),
        ]
        report = analyze_bars(bars, timeframe="1h", adjustment_mode="as_traded")
        self.assertTrue(report.ok)
        self.assertEqual(report.quality_verdict, "PASS")
        pub = report.public_dict()
        self.assertEqual(pub["qualityVerdict"], "PASS")
        self.assertEqual(pub["adjustmentMode"], "as_traded")
        self.assertTrue(pub["truth"]["parsed_csv_is_not_quality_pass"])

    def test_fail_ohlc_invariant(self) -> None:
        bars = [_bar("2024-01-01T00:00:00+00:00", o=10, h=9, l=8, c=9.5)]  # high < open
        report = analyze_bars(bars, timeframe="1h")
        self.assertFalse(report.ok)
        self.assertEqual(report.quality_verdict, "FAIL")
        self.assertTrue(report.ohlc_violations)

    def test_fail_negative_price_and_volume(self) -> None:
        bars = [_bar("2024-01-01T00:00:00+00:00", o=-1, h=2, l=-2, c=1, v=-5)]
        report = analyze_bars(bars, timeframe="1h")
        self.assertEqual(report.quality_verdict, "FAIL")
        self.assertTrue(report.negative_prices)
        self.assertTrue(report.negative_volumes)

    def test_warn_on_gap(self) -> None:
        bars = [
            _bar("2024-01-01T00:00:00+00:00"),
            _bar("2024-01-10T00:00:00+00:00"),
        ]
        report = analyze_bars(bars, timeframe="1h")
        self.assertTrue(report.ok)
        self.assertEqual(report.quality_verdict, "WARN")
        self.assertGreater(len(report.gaps), 0)

    def test_empty_is_fail(self) -> None:
        report = analyze_bars([], timeframe="1h")
        self.assertEqual(report.quality_verdict, "FAIL")
        self.assertFalse(report.ok)


class QuoteQualityW06Tests(unittest.TestCase):
    def test_crossed_market_fail(self) -> None:
        out = analyze_quote_snapshot([{"bid": 10.5, "ask": 10.0, "seq": 1}])
        self.assertEqual(out["qualityVerdict"], "FAIL")
        self.assertEqual(out["crossedMarkets"], 1)
        self.assertTrue(out["truth"]["ohlcv_is_not_orderbook"])

    def test_empty_quotes_unmeasured(self) -> None:
        out = analyze_quote_snapshot([])
        self.assertEqual(out["qualityVerdict"], "UNMEASURED")

    def test_clean_quotes_pass(self) -> None:
        out = analyze_quote_snapshot(
            [
                {"bid": 10.0, "ask": 10.1, "seq": 1},
                {"bid": 10.05, "ask": 10.15, "seq": 2},
            ]
        )
        self.assertEqual(out["qualityVerdict"], "PASS")


class PitFabricW06Tests(unittest.TestCase):
    def test_filter_bars_as_of(self) -> None:
        bars = [
            _bar("2024-01-01T00:00:00+00:00"),
            _bar("2024-01-02T00:00:00+00:00"),
            _bar("2024-01-03T00:00:00+00:00"),
        ]
        kept = filter_bars_as_of(bars, as_of="2024-01-02T00:00:00+00:00")
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[-1].ts, "2024-01-02T00:00:00+00:00")

    def test_observations_fail_closed_missing_future(self) -> None:
        bars = [
            _bar("2024-01-01T00:00:00+00:00"),
            _bar("2024-06-01T00:00:00+00:00"),
        ]
        obs = bars_to_pit_observations(bars, symbol="BTCUSDT", adjustment_mode="as_traded")
        kept = filter_observations_as_of(obs, as_of="2024-03-01T00:00:00+00:00")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].event_ts, "2024-01-01T00:00:00+00:00")

    def test_revision_identity_and_quality_labels(self) -> None:
        bars = [_bar("2024-01-01T00:00:00+00:00"), _bar("2024-01-01T01:00:00+00:00")]
        report = analyze_bars(bars, timeframe="1h", adjustment_mode="split_adjusted")
        rev = build_revision_identity(
            revision_id="rev-1",
            content_hash="abc",
            published_at="2024-01-02T00:00:00+00:00",
            available_at="2024-01-02T00:00:00+00:00",
            survivorship_mode="point_in_time",
        )
        payload = quality_with_pit_labels(
            report,
            adjustment_mode="split_adjusted",
            survivorship_mode="point_in_time",
            revision=rev,
        )
        self.assertEqual(payload["adjustmentMode"], "split_adjusted")
        self.assertEqual(payload["survivorshipMode"], "point_in_time")
        self.assertEqual(payload["revision"]["revision_id"], "rev-1")
        self.assertTrue(payload["truth"]["survivorship_bias_must_be_labelled"])

    def test_survivorship_membership_pit(self) -> None:
        uni = PointInTimeUniverse(
            [
                MembershipEvent("AAA", MembershipEventKind.LISTED, "2020-01-01T00:00:00+00:00"),
                MembershipEvent("BBB", MembershipEventKind.LISTED, "2020-01-01T00:00:00+00:00"),
                MembershipEvent("BBB", MembershipEventKind.DELISTED, "2022-01-01T00:00:00+00:00"),
            ]
        )
        before = survivorship_membership_as_of(uni, as_of="2021-06-01T00:00:00+00:00")
        after = survivorship_membership_as_of(uni, as_of="2023-01-01T00:00:00+00:00")
        self.assertEqual(before["symbols"], ["AAA", "BBB"])
        self.assertEqual(after["symbols"], ["AAA"])
        self.assertTrue(before["truth"]["point_in_time_default"])


class MarketDataStoreQualityW06Tests(unittest.TestCase):
    def test_inspect_path_exposes_quality_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src = root / "BTCUSDT_1h.csv"
            src.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,10,11,9,10.5,100\n"
                "2024-01-01T01:00:00+00:00,10.5,11.5,10,11,120\n",
                encoding="utf-8",
            )
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root)
            source = data.inspect_path("BTCUSDT_1h.csv", register=True)
            self.assertEqual(source.status, "READY")
            self.assertEqual(source.metadata.get("qualityVerdict"), "PASS")
            quality = source.metadata.get("quality") or {}
            self.assertEqual(quality.get("qualityVerdict"), "PASS")
            self.assertTrue((quality.get("truth") or {}).get("parsed_csv_is_not_quality_pass"))

    def test_inspect_path_fails_broken_ohlc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            src = root / "BAD_1h.csv"
            src.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,10,9,8,9.5,100\n",
                encoding="utf-8",
            )
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root)
            source = data.inspect_path("BAD_1h.csv", register=True)
            self.assertEqual(source.status, "INVALID")
            self.assertEqual(source.metadata.get("qualityVerdict"), "FAIL")


if __name__ == "__main__":
    unittest.main()
