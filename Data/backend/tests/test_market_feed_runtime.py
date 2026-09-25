"""Feed runtime + MarketStreamAdapter tests with FakeWebSocket (no live network)."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from Data.modules.market_sim.feed.runtime import FeedRuntime
from Data.modules.market_sim.feed.types import FeedConnectionState
from Data.modules.market_sim.market_event import MarketEvent, MarketEventType
from Data.modules.provider_io.adapters.market_stream import (
    MarketStreamAdapter,
    normalize_binance_stream_message,
)
from Data.modules.provider_io.policy import DeadlineBudget, ProviderPolicyRegistry, ProviderIoSettings
from Data.modules.provider_io.types import ProviderRequest


class FakeWebSocket:
    """Deterministic WS stand-in for websockets.sync.client.connect."""

    def __init__(self, messages: list[Any], *, fail_after: int | None = None) -> None:
        self.messages = list(messages)
        self.fail_after = fail_after
        self.recv_count = 0
        self.closed = False
        self.pings = 0
        self._lock = threading.Lock()

    def recv(self, timeout: float | None = None) -> str:
        del timeout
        with self._lock:
            if self.closed:
                raise ConnectionError("closed")
            if self.fail_after is not None and self.recv_count >= self.fail_after:
                raise ConnectionError("simulated disconnect")
            if not self.messages:
                raise TimeoutError("idle")
            self.recv_count += 1
            msg = self.messages.pop(0)
            if isinstance(msg, Exception):
                raise msg
            if isinstance(msg, (dict, list)):
                return json.dumps(msg)
            return str(msg)

    def ping(self) -> None:
        self.pings += 1

    def close(self) -> None:
        self.closed = True


class CountingCheckpointTransport:
    """Not used for WS — counts SQLite writes via instrumenting adapter checkpoint path."""


def _trade(sym: str, trade_id: int, price: float = 100.0, ts_ms: int = 1_700_000_000_000) -> dict:
    return {
        "stream": f"{sym.lower()}@trade",
        "data": {
            "e": "trade",
            "s": sym.upper(),
            "t": trade_id,
            "p": str(price),
            "q": "0.01",
            "T": ts_ms + trade_id,
            "E": ts_ms + trade_id,
            "m": False,
        },
    }


def _kline(sym: str, open_ms: int, *, closed: bool = True, price: float = 100.0) -> dict:
    return {
        "stream": f"{sym.lower()}@kline_1m",
        "data": {
            "e": "kline",
            "s": sym.upper(),
            "E": open_ms + 60_000,
            "k": {
                "t": open_ms,
                "T": open_ms + 59_999,
                "s": sym.upper(),
                "i": "1m",
                "o": str(price),
                "h": str(price + 1),
                "l": str(price - 1),
                "c": str(price + 0.5),
                "v": "5.0",
                "x": closed,
            },
        },
    }


class _NullClients:
    def client(self, name: str = "default") -> Any:
        del name

        class _C:
            def request(self, *a, **k):
                raise AssertionError("HTTP should not be called in this test")

        return _C()


class _NullCredential:
    headers: dict = {}
    extra: dict = {}


class MarketFeedRuntimeTests(unittest.TestCase):
    def test_normalize_trade_and_kline(self) -> None:
        trade = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 1)),
            provider_id="binance_public",
            connection_id="c1",
        )
        assert trade is not None
        self.assertEqual(trade.event_type, MarketEventType.TRADE)
        self.assertEqual(trade.symbol, "BTCUSDT")
        self.assertEqual(trade.sequence, 1)

        bar = normalize_binance_stream_message(
            json.dumps(_kline("BTCUSDT", 1_700_000_000_000, closed=True)),
            provider_id="binance_public",
            connection_id="c1",
        )
        assert bar is not None
        self.assertEqual(bar.event_type, MarketEventType.BAR_CLOSE)
        self.assertIsNotNone(bar.bar)

    def test_connect_normalize_multi_symbol(self) -> None:
        messages = [
            _trade("BTCUSDT", 1),
            _trade("ETHUSDT", 1),
            _kline("BTCUSDT", 1_700_000_000_000),
        ]
        ws = FakeWebSocket(messages)
        ingested: list[MarketEvent] = []

        def connect(uri: str, **kwargs: Any) -> FakeWebSocket:
            del uri, kwargs
            return ws

        adapter = MarketStreamAdapter(websocket_connect=connect, sleep=lambda _s: None)
        result = adapter.execute(
            ProviderRequest(
                provider="binance_public",
                capability="market.stream",
                payload={
                    "symbols": ["BTCUSDT", "ETHUSDT"],
                    "feed_id": "feed_test",
                    "connection_id": "conn_test",
                    "max_runtime_seconds": 2.0,
                    "recv_timeout_seconds": 0.01,
                    "checkpoint_interval_seconds": 60.0,
                    "gap_recovery_enabled": False,
                },
            ),
            clients=_NullClients(),  # type: ignore[arg-type]
            credential=_NullCredential(),  # type: ignore[arg-type]
            policy=ProviderPolicyRegistry(ProviderIoSettings.load()),
            budget=DeadlineBudget(total_seconds=5.0),
            cancel_check=lambda: ws.recv_count >= 3 and not ws.messages,
            ingest=ingested.append,
        )
        self.assertIn(result.status, {"succeeded", "cancelled"})
        symbols = {e.symbol for e in ingested}
        self.assertIn("BTCUSDT", symbols)
        self.assertIn("ETHUSDT", symbols)
        self.assertGreaterEqual(len(ingested), 3)

    def test_duplicate_and_out_of_order_via_runtime(self) -> None:
        runtime = FeedRuntime()
        session = runtime.create_subscription(
            provider_id="binance_public",
            symbols=["BTCUSDT"],
        )
        session.set_status(FeedConnectionState.LIVE)
        e1 = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 10)),
            provider_id="binance_public",
            connection_id="c",
        )
        e2 = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 10)),
            provider_id="binance_public",
            connection_id="c",
        )
        e_late = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 9)),
            provider_id="binance_public",
            connection_id="c",
        )
        e_gap = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 12)),
            provider_id="binance_public",
            connection_id="c",
        )
        assert e1 and e2 and e_late and e_gap
        self.assertTrue(session.ingest(e1)["accepted"])
        self.assertFalse(session.ingest(e2)["accepted"])
        late = session.ingest(e_late)
        self.assertTrue(late["accepted"])
        gap = session.ingest(e_gap)
        self.assertEqual(gap["disposition"], "GAP_DETECTED")
        self.assertFalse(session.allows_new_risk())

    def test_reconnect_and_shutdown(self) -> None:
        calls = {"n": 0}
        sockets: list[FakeWebSocket] = []

        def connect(uri: str, **kwargs: Any) -> FakeWebSocket:
            del uri, kwargs
            calls["n"] += 1
            if calls["n"] == 1:
                ws = FakeWebSocket([_trade("BTCUSDT", 1)], fail_after=1)
            else:
                ws = FakeWebSocket([_trade("BTCUSDT", 2)])
            sockets.append(ws)
            return ws

        ingested: list[MarketEvent] = []
        stop = {"v": False}

        def cancel() -> bool:
            return stop["v"] or len(ingested) >= 2

        adapter = MarketStreamAdapter(
            websocket_connect=connect,
            sleep=lambda _s: None,
        )
        result = adapter.execute(
            ProviderRequest(
                provider="binance_public",
                capability="market.stream",
                payload={
                    "symbols": ["BTCUSDT"],
                    "feed_id": "feed_re",
                    "max_runtime_seconds": 3.0,
                    "base_backoff_seconds": 0.01,
                    "max_backoff_seconds": 0.05,
                    "gap_recovery_enabled": False,
                    "recv_timeout_seconds": 0.01,
                },
            ),
            clients=_NullClients(),  # type: ignore[arg-type]
            credential=_NullCredential(),  # type: ignore[arg-type]
            policy=ProviderPolicyRegistry(ProviderIoSettings.load()),
            budget=DeadlineBudget(total_seconds=5.0),
            cancel_check=cancel,
            ingest=ingested.append,
        )
        self.assertGreaterEqual(calls["n"], 2)
        self.assertGreaterEqual(len(ingested), 2)
        self.assertIn(result.structured["status"], {"STOPPED", "LIVE", "STOPPING"})

    def test_stale_and_backpressure_bounded_buffer(self) -> None:
        runtime = FeedRuntime()
        session = runtime.create_subscription(
            provider_id="binance_public",
            symbols=["BTCUSDT"],
            stale_after_seconds=0.05,
            ring_buffer_events=16,
        )
        session.set_status(FeedConnectionState.LIVE)
        for i in range(40):
            ev = normalize_binance_stream_message(
                json.dumps(_trade("BTCUSDT", i + 1, ts_ms=1_700_000_000_000 + i)),
                provider_id="binance_public",
                connection_id="c",
            )
            assert ev is not None
            # Force old received_at for stale check after loop.
            ev.received_at = "2020-01-01T00:00:00+00:00"
            session.ingest(ev)
        self.assertTrue(session.check_stale())
        self.assertEqual(session.sub.status, FeedConnectionState.STALE)
        buf = session.buffers.buffer("BTCUSDT")
        self.assertLessEqual(len(buf), 16)

    def test_high_rate_ingest_does_not_sqlite_write_per_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leviathan.db"
            messages = [_trade("BTCUSDT", i + 1) for i in range(50)]
            ws = FakeWebSocket(messages)

            def connect(uri: str, **kwargs: Any) -> FakeWebSocket:
                del uri, kwargs
                return ws

            adapter = MarketStreamAdapter(websocket_connect=connect, sleep=lambda _s: None)
            result = adapter.execute(
                ProviderRequest(
                    provider="binance_public",
                    capability="market.stream",
                    payload={
                        "symbols": ["BTCUSDT"],
                        "feed_id": "feed_ckpt",
                        "db_path": str(db_path),
                        "max_runtime_seconds": 2.0,
                        "checkpoint_interval_seconds": 60.0,  # coalesce hard
                        "gap_recovery_enabled": False,
                        "recv_timeout_seconds": 0.01,
                    },
                ),
                clients=_NullClients(),  # type: ignore[arg-type]
                credential=_NullCredential(),  # type: ignore[arg-type]
                policy=ProviderPolicyRegistry(ProviderIoSettings.load()),
                budget=DeadlineBudget(total_seconds=5.0),
                cancel_check=lambda: not ws.messages and ws.recv_count >= 50,
                # No ingest callback → checkpoint path
            )
            metrics = result.structured["metrics"]
            self.assertEqual(int(metrics["events_normalized"]), 50)
            # Force write at end + optional interval writes must be << event count.
            writes = int(metrics.get("checkpoint_writes") or 0)
            skipped = int(metrics.get("checkpoint_skipped") or 0)
            self.assertLess(writes, 50)
            self.assertGreaterEqual(skipped + writes, 50)
            self.assertLessEqual(writes, 3)

    def test_gap_sets_degraded_and_blocks_risk(self) -> None:
        runtime = FeedRuntime()
        session = runtime.create_subscription(
            provider_id="binance_public",
            symbols=["BTCUSDT"],
        )
        session.set_status(FeedConnectionState.LIVE)
        a = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 1)),
            provider_id="binance_public",
            connection_id="c",
        )
        b = normalize_binance_stream_message(
            json.dumps(_trade("BTCUSDT", 5)),
            provider_id="binance_public",
            connection_id="c",
        )
        assert a and b
        session.ingest(a)
        session.ingest(b)
        self.assertEqual(session.sub.status, FeedConnectionState.DEGRADED)
        self.assertFalse(session.allows_new_risk())


if __name__ == "__main__":
    unittest.main()
