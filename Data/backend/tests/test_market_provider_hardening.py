"""Hardening tests for market provider HTTP transport + Binance pagination."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from Data.modules.common.retry import RetryPolicy
from Data.modules.market_sim.providers import BinancePublicProvider
from Data.modules.market_sim.providers.http_transport import (
    HttpResponse,
    request_with_retry,
)
from Data.modules.market_sim.types import MarketSimError


class FakeTransport:
    """Scripted HTTP transport for deterministic provider tests."""

    def __init__(self, script: list[HttpResponse | Exception] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "timeout": timeout}
        )
        if not self.script:
            raise AssertionError(f"Unexpected request: {method} {url}")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _kline_row(open_ms: int, price: float = 100.0) -> list[Any]:
    return [
        open_ms,
        str(price),
        str(price + 1),
        str(price - 1),
        str(price + 0.5),
        "10.0",
        open_ms + 59_999,
        "0",
        0,
        "0",
        "0",
        "0",
    ]


class MarketProviderHardeningTests(unittest.TestCase):
    def test_pagination_beyond_1000(self) -> None:
        page1 = [_kline_row(1_700_000_000_000 + i * 60_000, 100 + i) for i in range(1000)]
        page2 = [_kline_row(1_700_000_000_000 + (1000 + i) * 60_000, 200 + i) for i in range(50)]
        import json

        transport = FakeTransport(
            [
                HttpResponse(200, json.dumps(page1).encode(), {}, url="https://data-api.binance.vision/a"),
                HttpResponse(200, json.dumps(page2).encode(), {}, url="https://data-api.binance.vision/b"),
            ]
        )
        provider = BinancePublicProvider(transport=transport, retry=RetryPolicy(max_attempts=2))
        bars = provider.fetch_historical("BTCUSDT", "1m", limit=1050)
        self.assertEqual(len(bars), 1050)
        self.assertGreaterEqual(len(transport.calls), 2)
        self.assertIn("startTime", transport.calls[1]["url"])

    def test_429_retry_after(self) -> None:
        sleeps: list[float] = []
        transport = FakeTransport(
            [
                HttpResponse(
                    429,
                    b"{}",
                    {"Retry-After": "1.5"},
                    url="https://data-api.binance.vision/x",
                ),
                HttpResponse(200, b"[]", {}, url="https://data-api.binance.vision/x"),
            ]
        )
        resp = request_with_retry(
            transport,
            "GET",
            "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1",
            retry=RetryPolicy(max_attempts=3, base_seconds=0.1, max_seconds=5.0, jitter_ratio=0.0),
            sleep=sleeps.append,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(sleeps)
        self.assertAlmostEqual(sleeps[0], 1.5, places=1)

    def test_backoff_exhaustion(self) -> None:
        transport = FakeTransport(
            [
                HttpResponse(503, b"nope", {}, url="https://data-api.binance.vision/x"),
                HttpResponse(503, b"nope", {}, url="https://data-api.binance.vision/x"),
            ]
        )
        with self.assertRaises(MarketSimError) as ctx:
            request_with_retry(
                transport,
                "GET",
                "https://data-api.binance.vision/api/v3/ping",
                retry=RetryPolicy(max_attempts=2, base_seconds=0.01, max_seconds=0.05, jitter_ratio=0.0),
                sleep=lambda _s: None,
            )
        self.assertEqual(ctx.exception.code, "PROVIDER_HTTP")

    def test_timeout_cancel(self) -> None:
        cancelled = {"v": False}

        class SlowTransport:
            def request(self, method, url, *, headers=None, timeout=None):
                time.sleep(0.01)
                cancelled["v"] = True
                raise MarketSimError("EXECUTION_CANCELLED", "Cancelled during market HTTP", http_status=499)

        with self.assertRaises(MarketSimError) as ctx:
            request_with_retry(
                SlowTransport(),
                "GET",
                "https://data-api.binance.vision/api/v3/ping",
                retry=RetryPolicy(max_attempts=3),
                cancel_check=lambda: True,
                sleep=lambda _s: None,
            )
        self.assertEqual(ctx.exception.code, "EXECUTION_CANCELLED")

    def test_dedupe_overlap_across_pages(self) -> None:
        import json

        # Overlapping bar at page boundary must be deduped.
        open0 = 1_700_000_000_000
        page1 = [_kline_row(open0 + i * 60_000) for i in range(3)]
        page2 = [_kline_row(open0 + i * 60_000) for i in range(2, 5)]  # overlap index 2
        transport = FakeTransport(
            [
                HttpResponse(200, json.dumps(page1).encode(), {}),
                HttpResponse(200, json.dumps(page2).encode(), {}),
                HttpResponse(200, b"[]", {}),
            ]
        )
        provider = BinancePublicProvider(transport=transport, retry=RetryPolicy(max_attempts=2))
        bars = provider.fetch_historical(
            "BTCUSDT",
            "1m",
            limit=10,
            start_ts="2023-11-14T22:13:20+00:00",
        )
        ts_list = [b.ts for b in bars]
        self.assertEqual(len(ts_list), len(set(ts_list)))

    def test_host_allowlist_blocks_unknown(self) -> None:
        transport = FakeTransport([])
        with self.assertRaises(MarketSimError) as ctx:
            request_with_retry(
                transport,
                "GET",
                "https://evil.example/api/v3/klines",
                retry=RetryPolicy(max_attempts=1),
            )
        self.assertEqual(ctx.exception.code, "NETWORK_BLOCKED")
        self.assertEqual(len(transport.calls), 0)


if __name__ == "__main__":
    unittest.main()
