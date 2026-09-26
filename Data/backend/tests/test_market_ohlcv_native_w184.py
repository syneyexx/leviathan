"""Tests for market.ohlcv_validate native pilot + Python helper."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.native_ohlcv import (
    try_native_ohlcv_validate,
    validate_ohlcv_optional_native,
)
from Data.modules.market_sim.ohlcv import validate_ohlcv_file
from Data.modules.workers.native_compute import resolve_native_binary


OHLCV_CSV = """timestamp,open,high,low,close,volume,symbol
2026-01-01T00:00:00Z,100,101,99,100.5,10,BTCUSDT
2026-01-01T00:01:00Z,100.5,102,100,101,12,BTCUSDT
2026-01-01T00:02:00Z,101,103,100.5,102,11,BTCUSDT
"""


class TestMarketOhlcvNativeW184(unittest.TestCase):
    def test_python_and_optional_native_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ohlcv.csv"
            path.write_text(OHLCV_CSV, encoding="utf-8")
            py = validate_ohlcv_file(path)
            self.assertTrue(py.ok)
            self.assertGreaterEqual(py.bar_count, 3)

            combined = validate_ohlcv_optional_native(path, prefer_native=False)
            self.assertTrue(combined.ok)

            binary = resolve_native_binary()
            native = try_native_ohlcv_validate(path)
            if binary is None:
                self.assertIsNone(native)
            else:
                self.assertIsNotNone(native)
                assert native is not None
                self.assertTrue(native.ok)
                self.assertEqual(native.bar_count, py.bar_count)


if __name__ == "__main__":
    unittest.main()
