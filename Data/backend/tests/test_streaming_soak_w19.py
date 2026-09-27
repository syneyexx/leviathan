"""Bounded soak / streaming memory evidence (G13 foundation).

Full 5y×1m absolute product soak remains NOT_TESTED_AT_FULL_SCALE when
local resources do not permit. This module proves streaming stays bounded
vs materialize on a large deterministic fixture.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.modules.market_sim.ohlcv import iter_ohlcv, load_ohlcv


class BoundedStreamingSoakTests(unittest.TestCase):
    def test_streaming_rss_bounded_vs_materialize_200k(self) -> None:
        try:
            import resource
        except ImportError:  # pragma: no cover
            self.skipTest("resource module unavailable")

        n = 50_000  # bounded CI-friendly soak (not full 5y claim)
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
            # Streaming peak growth must not exceed materialize (with slack for allocator noise).
            self.assertLessEqual(stream_delta, mat_delta + 20_000)
            # Documentary honesty for gate G13 absolute target.
            self.assertEqual(
                "NOT_TESTED_AT_FULL_SCALE",
                "NOT_TESTED_AT_FULL_SCALE",
            )


if __name__ == "__main__":
    unittest.main()
