"""Equity-session 5y×1m-equivalent streaming soak (G13).

Crypto 24/7 5y×1m (~2.6M bars) remains NOT_TESTED_AT_FULL_SCALE when not run.
Equity cash-session 5y×1m ≈ 5×252×390 ≈ 491k bars — proven via streaming.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.ohlcv import iter_ohlcv, load_ohlcv


class BoundedStreamingSoakTests(unittest.TestCase):
    def test_streaming_rss_bounded_vs_materialize_50k(self) -> None:
        try:
            import resource
        except ImportError:  # pragma: no cover
            self.skipTest("resource module unavailable")

        n = 50_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            with path.open("w", encoding="utf-8") as fh:
                fh.write("ts,open,high,low,close,volume\n")
                px = 100.0
                for i in range(n):
                    ts = (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
                    px += 0.01 if i % 2 == 0 else -0.005
                    fh.write(f"{ts},{px},{px + 0.1},{px - 0.1},{px},1000\n")

            def rss_kb() -> int:
                return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

            before = rss_kb()
            count = sum(1 for _ in iter_ohlcv(path))
            stream_delta = rss_kb() - before
            self.assertEqual(count, n)

            before_m = rss_kb()
            mats = load_ohlcv(path)
            mat_delta = rss_kb() - before_m
            self.assertEqual(len(mats), n)
            self.assertLessEqual(stream_delta, mat_delta + 20_000)

    def test_equity_5y_1m_equivalent_stream_no_oom(self) -> None:
        """Stream ≥ equity-session 5y×1m bar count without RSS growth / OOM."""
        try:
            import resource
        except ImportError:  # pragma: no cover
            self.skipTest("resource module unavailable")

        # 5 * 252 trading days * 390 session minutes ≈ 491,400
        n = 500_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eq5y1m.csv"
            start = datetime(2019, 1, 1, 14, 30, tzinfo=timezone.utc)
            with path.open("w", encoding="utf-8") as fh:
                fh.write("ts,open,high,low,close,volume\n")
                px = 100.0
                for i in range(n):
                    ts = (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
                    px += 0.001 if i % 2 == 0 else -0.0005
                    fh.write(f"{ts},{px:.6f},{px + 0.05:.6f},{px - 0.05:.6f},{px:.6f},1000\n")

            before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            count = sum(1 for _ in iter_ohlcv(path))
            after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            self.assertEqual(count, n)
            # Streaming must not accumulate bar materialization in RSS.
            self.assertLessEqual(after - before, 50_000)  # ≤ ~50MB slack (KB on Linux)


if __name__ == "__main__":
    unittest.main()
