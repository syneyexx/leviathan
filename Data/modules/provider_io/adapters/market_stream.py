"""Binance public combined-stream adapter — market data only (no order/trading endpoints).

Long-lived WebSocket I/O for capability ``market.stream``. Domain normalization
targets ``MarketEvent``; CONTROL-sized SQLite checkpoints are coalesced (never
one write per tick). Inject ``websocket_connect`` for deterministic tests.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from Data.modules.common.retry import RetryPolicy, compute_backoff_seconds
from Data.modules.market_sim.feed.types import FeedConnectionState
from Data.modules.market_sim.market_event import (
    MarketBarPayload,
    MarketEvent,
    MarketEventProvenance,
    MarketEventType,
    MarketEventTruth,
    hash_provider_payload,
)
from Data.modules.provider_io.clients import ProviderClientPool
from Data.modules.provider_io.credentials import ResolvedCredential
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.policy import DeadlineBudget, ProviderPolicyRegistry
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import ProviderExecutionResult, ProviderRequest


CancelCheck = Callable[[], bool]
EmitFn = Callable[[str, dict[str, Any]], None]
IngestFn = Callable[[MarketEvent], Any]
WebsocketConnect = Callable[..., Any]

BINANCE_WS_COMBINED = "wss://stream.binance.com:9443/stream"
BINANCE_REST_BASE = "https://data-api.binance.vision"
ALLOWED_WS_HOSTS = frozenset({"stream.binance.com", "data-stream.binance.vision"})
FORBIDDEN_PATH_MARKERS = (
    "/order",
    "/orders",
    "/account",
    "/userDataStream",
    "/sapi/",
    "/api/v3/order",
    "/fapi/",
    "/dapi/",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ms_to_iso(ms: int | float | None) -> str | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (TypeError, ValueError, OSError):
        return None


def _default_websocket_connect(uri: str, **kwargs: Any) -> Any:
    from websockets.sync.client import connect

    return connect(uri, **kwargs)


def build_combined_stream_url(
    symbols: list[str],
    *,
    stream_kinds: list[str] | None = None,
    base: str = BINANCE_WS_COMBINED,
) -> str:
    """Build Binance PUBLIC combined-stream URL (kline + trade only)."""
    kinds = list(stream_kinds or ["kline_1m", "trade"])
    streams: list[str] = []
    for sym in symbols:
        s = sym.lower().replace("/", "").replace("-", "")
        for kind in kinds:
            k = kind.lower().strip()
            if k in {"trade", "trades"}:
                streams.append(f"{s}@trade")
            elif k.startswith("kline"):
                interval = k.split("_", 1)[1] if "_" in k else "1m"
                streams.append(f"{s}@kline_{interval}")
            elif k.startswith("kline_"):
                streams.append(f"{s}@{k}")
            else:
                # Refuse unknown / trading streams.
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                    f"Unsupported market stream kind (market data only): {kind}",
                    provider="binance_public",
                )
    if not streams:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_INVALID_REQUEST,
            "market.stream requires at least one stream",
            provider="binance_public",
        )
    # Combined streams use query param ?streams=a/b/c
    joined = "/".join(streams)
    return f"{base}?streams={joined}"


def assert_market_data_only_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host and host not in ALLOWED_WS_HOSTS and not any(
        host.endswith("." + h) for h in ALLOWED_WS_HOSTS
    ):
        raise ProviderError(
            ProviderErrorCode.PROVIDER_INVALID_REQUEST,
            f"WebSocket host not allowlisted for market streams: {host}",
            provider="binance_public",
            http_status=403,
        )
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker.lower() in path or marker.lower() in url.lower():
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                f"Refusing non-market-data stream endpoint containing {marker}",
                provider="binance_public",
                http_status=403,
            )


def normalize_binance_stream_message(
    raw: Any,
    *,
    provider_id: str,
    connection_id: str,
    received_at: str | None = None,
) -> MarketEvent | None:
    """Map a Binance combined-stream JSON message to MarketEvent (or None for ping/noise)."""
    received = received_at or _utc_now()
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text_strip = text.strip()
    if not text_strip:
        return None
    # Heartbeat / control frames as plain text
    if text_strip.upper() in {"PING", "PONG"}:
        return MarketEvent(
            event_id=f"hb_{hash_provider_payload(text_strip)[:16]}",
            provider_id=provider_id,
            connection_id=connection_id,
            symbol="*",
            event_type=MarketEventType.HEARTBEAT,
            exchange_ts=received,
            received_at=received,
            available_at=received,
            status=text_strip.upper(),
            provenance=MarketEventProvenance(
                provider=provider_id,
                stream="heartbeat",
                transport="websocket",
            ),
            truth=MarketEventTruth(),
        )
    try:
        payload = json.loads(text_strip)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    # Combined stream wraps as {"stream": "...", "data": {...}}
    data = payload.get("data") if "data" in payload and isinstance(payload.get("data"), dict) else payload
    stream_name = str(payload.get("stream") or "")
    event_type_code = str(data.get("e") or "")

    if event_type_code == "trade" or "@trade" in stream_name:
        sym = str(data.get("s") or "").upper()
        trade_id = data.get("t")
        price = float(data["p"]) if data.get("p") is not None else None
        size = float(data["q"]) if data.get("q") is not None else None
        exchange_ts = _ms_to_iso(data.get("T") or data.get("E"))
        eid = f"trade_{sym}_{trade_id}" if trade_id is not None else f"trade_{hash_provider_payload(data)[:20]}"
        return MarketEvent(
            event_id=eid,
            provider_id=provider_id,
            connection_id=connection_id,
            symbol=sym,
            event_type=MarketEventType.TRADE,
            exchange_ts=exchange_ts,
            received_at=received,
            available_at=received,
            sequence=int(trade_id) if trade_id is not None else None,
            sequence_source="binance.trade_id",
            price=price,
            size=size,
            provider_payload_hash=hash_provider_payload(data),
            provenance=MarketEventProvenance(
                provider=provider_id,
                endpoint="combined",
                stream=stream_name or "trade",
                transport="websocket",
            ),
            truth=MarketEventTruth(),
            metadata={"buyer_is_maker": data.get("m")},
        )

    if event_type_code == "kline" or "@kline" in stream_name:
        k = data.get("k") if isinstance(data.get("k"), dict) else data
        sym = str(k.get("s") or data.get("s") or "").upper()
        interval = str(k.get("i") or "1m")
        is_closed = bool(k.get("x"))
        open_ts = _ms_to_iso(k.get("t"))
        close_ts = _ms_to_iso(k.get("T"))
        bar = MarketBarPayload(
            open=float(k["o"]) if k.get("o") is not None else None,
            high=float(k["h"]) if k.get("h") is not None else None,
            low=float(k["l"]) if k.get("l") is not None else None,
            close=float(k["c"]) if k.get("c") is not None else None,
            volume=float(k["v"]) if k.get("v") is not None else None,
            timeframe=interval,
            open_ts=open_ts,
            close_ts=close_ts,
        )
        seq = int(k["t"]) if k.get("t") is not None else None
        eid = f"kline_{sym}_{interval}_{k.get('t')}_{'c' if is_closed else 'u'}"
        return MarketEvent(
            event_id=eid,
            provider_id=provider_id,
            connection_id=connection_id,
            symbol=sym,
            event_type=MarketEventType.BAR_CLOSE if is_closed else MarketEventType.BAR_UPDATE,
            exchange_ts=close_ts or open_ts or _ms_to_iso(data.get("E")),
            received_at=received,
            available_at=received,
            sequence=seq,
            sequence_source="binance.kline_open_ms",
            price=bar.close,
            size=bar.volume,
            bar=bar,
            provider_payload_hash=hash_provider_payload(k),
            provenance=MarketEventProvenance(
                provider=provider_id,
                endpoint="combined",
                stream=stream_name or f"kline_{interval}",
                transport="websocket",
            ),
            truth=MarketEventTruth(),
        )

    # Ignore result/subscribe acks and unknown events.
    if "result" in payload or "id" in payload and "e" not in data:
        return None
    return None


class _CheckpointWriter:
    """Coalesced CONTROL-sized snapshot writer — never one row per tick."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        feed_id: str,
        min_interval_seconds: float = 5.0,
        max_checkpoints: int = 64,
    ) -> None:
        self.db_path = Path(db_path)
        self.feed_id = feed_id
        self.min_interval_seconds = max(0.5, float(min_interval_seconds))
        self.max_checkpoints = max(4, int(max_checkpoints))
        self._last_write = 0.0
        self.write_count = 0
        self.skipped_count = 0
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        return open_sqlite_connection(self.db_path, set_wal=False)

    def _ensure_tables(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_feed_checkpoints (
                    feed_id TEXT NOT NULL,
                    written_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL DEFAULT '{}',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (feed_id, written_at)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def maybe_write(
        self,
        snapshot: dict[str, Any],
        metrics: dict[str, Any],
        *,
        force: bool = False,
        now: float | None = None,
    ) -> bool:
        t = now if now is not None else time.monotonic()
        if not force and (t - self._last_write) < self.min_interval_seconds:
            self.skipped_count += 1
            return False
        written_at = _utc_now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_feed_checkpoints(
                    feed_id, written_at, snapshot_json, metrics_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    self.feed_id,
                    written_at,
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    json.dumps(metrics, ensure_ascii=False, default=str),
                ),
            )
            # Bound retention per feed.
            rows = conn.execute(
                """
                SELECT written_at FROM market_feed_checkpoints
                WHERE feed_id=? ORDER BY written_at DESC
                """,
                (self.feed_id,),
            ).fetchall()
            if len(rows) > self.max_checkpoints:
                for stale in rows[self.max_checkpoints :]:
                    conn.execute(
                        "DELETE FROM market_feed_checkpoints WHERE feed_id=? AND written_at=?",
                        (self.feed_id, stale[0]),
                    )
            conn.commit()
        finally:
            conn.close()
        self._last_write = t
        self.write_count += 1
        return True


class MarketStreamAdapter:
    """provider_io adapter for capability ``market.stream`` / ``market.stream.stop``."""

    name = "market_stream"

    def __init__(
        self,
        *,
        websocket_connect: WebsocketConnect | None = None,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._websocket_connect = websocket_connect or _default_websocket_connect
        self._sleep = sleep or time.sleep
        self._rng = rng or random.Random()

    def execute(
        self,
        request: ProviderRequest,
        *,
        clients: ProviderClientPool,
        credential: ResolvedCredential,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        stream_store: ProviderStreamStore | None = None,
        cancel_check: CancelCheck | None = None,
        emit: EmitFn | None = None,
        ingest: IngestFn | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> ProviderExecutionResult:
        del credential, stream_store
        ctx = dict(ctx or {})
        payload = dict(request.payload or {})
        capability = str(request.capability or "").strip()

        if capability in {"market.stream.stop", "stream.stop"}:
            return self._execute_stop(request, payload, emit=emit or ctx.get("emit"))

        return self._execute_stream(
            request,
            payload,
            clients=clients,
            policy=policy,
            budget=budget,
            cancel_check=cancel_check,
            emit=emit or ctx.get("emit"),
            ingest=ingest or payload.get("ingest") or ctx.get("ingest"),
            ctx=ctx,
        )

    def _execute_stop(
        self,
        request: ProviderRequest,
        payload: dict[str, Any],
        *,
        emit: EmitFn | None,
    ) -> ProviderExecutionResult:
        feed_id = str(payload.get("feed_id") or "").strip()
        if emit:
            emit(
                "market.feed.stopping",
                {"feed_id": feed_id, "provider": request.provider, "capability": "market.stream.stop"},
            )
        return ProviderExecutionResult(
            status="succeeded",
            structured={
                "feed_id": feed_id,
                "status": FeedConnectionState.STOPPING.value,
                "action": "stop_requested",
            },
            provider=request.provider,
            finish_reason="stop",
            metadata={"capability": "market.stream.stop"},
        )

    def _execute_stream(
        self,
        request: ProviderRequest,
        payload: dict[str, Any],
        *,
        clients: ProviderClientPool,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        cancel_check: CancelCheck | None,
        emit: EmitFn | None,
        ingest: IngestFn | None,
        ctx: dict[str, Any],
    ) -> ProviderExecutionResult:
        provider_id = str(
            payload.get("provider_id") or request.provider or "binance_public"
        ).strip()
        symbols_raw = payload.get("symbols") or payload.get("symbol") or []
        if isinstance(symbols_raw, str):
            symbols = [symbols_raw]
        else:
            symbols = [str(s).upper() for s in list(symbols_raw)]
        if not symbols:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "market.stream requires symbols",
                provider=provider_id,
            )
        stream_kinds = list(payload.get("stream_kinds") or ["kline_1m", "trade"])
        feed_id = str(payload.get("feed_id") or f"feed_{os.getpid()}")
        connection_id = str(payload.get("connection_id") or f"conn_{os.getpid()}")
        max_runtime = float(payload.get("max_runtime_seconds") or 3600.0)
        gap_recovery_enabled = bool(payload.get("gap_recovery_enabled", True))
        checkpoint_interval = float(payload.get("checkpoint_interval_seconds") or 5.0)
        recv_timeout = float(payload.get("recv_timeout_seconds") or 5.0)
        ping_interval = float(payload.get("ping_interval_seconds") or 20.0)
        max_backoff = float(payload.get("max_backoff_seconds") or 60.0)
        base_backoff = float(payload.get("base_backoff_seconds") or 0.5)
        ws_url = str(payload.get("ws_url") or "").strip() or build_combined_stream_url(
            symbols, stream_kinds=stream_kinds
        )
        assert_market_data_only_url(ws_url)

        # Resolve ingest callback from payload/ctx (tests inject callables).
        if ingest is None and callable(payload.get("ingest_callback")):
            ingest = payload["ingest_callback"]
        if emit is None and callable(ctx.get("emit")):
            emit = ctx["emit"]
        if emit is None and callable(payload.get("emit")):
            emit = payload["emit"]

        db_path = str(
            payload.get("db_path")
            or ctx.get("db_path")
            or os.environ.get("LEVIATHAN_DB_PATH")
            or ""
        )
        checkpoint: _CheckpointWriter | None = None
        if db_path and not ingest:
            checkpoint = _CheckpointWriter(
                db_path,
                feed_id=feed_id,
                min_interval_seconds=checkpoint_interval,
            )

        state = FeedConnectionState.DISCONNECTED
        metrics: dict[str, Any] = {
            "events_received": 0,
            "events_normalized": 0,
            "reconnect_count": 0,
            "gap_recovery_bars": 0,
            "checkpoint_writes": 0,
            "heartbeat_count": 0,
            "last_exchange_ts": None,
            "status": state.value,
        }
        coalesced_snapshot: dict[str, Any] = {
            "feed_id": feed_id,
            "connection_id": connection_id,
            "symbols": symbols,
            "provider_id": provider_id,
            "last_event": None,
            "status": state.value,
        }

        def set_state(new_state: FeedConnectionState, *, error: str = "") -> None:
            nonlocal state
            state = new_state
            metrics["status"] = new_state.value
            coalesced_snapshot["status"] = new_state.value
            if error:
                metrics["error"] = error
            if emit:
                emit(
                    f"market.feed.{new_state.value.lower()}",
                    {
                        "feed_id": feed_id,
                        "connection_id": connection_id,
                        "provider_id": provider_id,
                        "status": new_state.value,
                        "error": error,
                    },
                )

        def cancelled() -> bool:
            if cancel_check and cancel_check():
                return True
            return False

        started = time.monotonic()
        deadline = started + max_runtime
        last_exchange_ts: str | None = None
        reconnect_attempt = 0
        ws_factory = payload.get("websocket_connect") or self._websocket_connect

        def run_gap_recovery(gap_from_iso: str | None, gap_to_iso: str | None) -> int:
            if not gap_recovery_enabled or not gap_from_iso:
                return 0
            try:
                from Data.modules.market_sim.providers.http_transport import (
                    HttpxTransport,
                    request_with_retry,
                )

                transport = HttpxTransport(
                    clients.client(name="market_stream_gap"),
                    provider=provider_id,
                )
                recovered = 0
                for sym in symbols:
                    params = {
                        "symbol": sym.replace("/", "").replace("-", ""),
                        "interval": "1m",
                        "limit": 1000,
                    }
                    # Convert ISO → ms for Binance REST
                    try:
                        start_ms = int(
                            datetime.fromisoformat(gap_from_iso.replace("Z", "+00:00")).timestamp()
                            * 1000
                        )
                        params["startTime"] = start_ms
                    except ValueError:
                        pass
                    if gap_to_iso:
                        try:
                            end_ms = int(
                                datetime.fromisoformat(
                                    gap_to_iso.replace("Z", "+00:00")
                                ).timestamp()
                                * 1000
                            )
                            params["endTime"] = end_ms
                        except ValueError:
                            pass
                    from urllib.parse import urlencode

                    url = f"{BINANCE_REST_BASE}/api/v3/klines?{urlencode(params)}"
                    resp = request_with_retry(
                        transport,
                        "GET",
                        url,
                        timeout=20.0,
                        retry=RetryPolicy(max_attempts=3, base_seconds=0.25, max_seconds=8.0),
                        cancel_check=cancel_check,
                        sleep=self._sleep,
                    )
                    rows = json.loads(resp.body.decode("utf-8"))
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        open_ms = int(row[0])
                        open_ts = _ms_to_iso(open_ms)
                        close_ts = _ms_to_iso(int(row[6])) if len(row) > 6 else open_ts
                        ev = MarketEvent(
                            event_id=f"gap_kline_{sym}_{open_ms}",
                            provider_id=provider_id,
                            connection_id=connection_id,
                            symbol=sym,
                            event_type=MarketEventType.BAR_CLOSE,
                            exchange_ts=close_ts,
                            received_at=_utc_now(),
                            available_at=_utc_now(),
                            sequence=open_ms,
                            sequence_source="binance.gap_recovery",
                            price=float(row[4]),
                            size=float(row[5]),
                            bar=MarketBarPayload(
                                open=float(row[1]),
                                high=float(row[2]),
                                low=float(row[3]),
                                close=float(row[4]),
                                volume=float(row[5]),
                                timeframe="1m",
                                open_ts=open_ts,
                                close_ts=close_ts,
                            ),
                            provenance=MarketEventProvenance(
                                provider=provider_id,
                                endpoint="api/v3/klines",
                                stream="gap_recovery",
                                transport="http",
                            ),
                            truth=MarketEventTruth(),
                            metadata={"gap_recovery": True},
                        )
                        if ingest:
                            ingest(ev)
                        recovered += 1
                metrics["gap_recovery_bars"] = int(metrics["gap_recovery_bars"]) + recovered
                if emit and recovered:
                    emit(
                        "market.feed.gap_recovery",
                        {
                            "feed_id": feed_id,
                            "recovered": recovered,
                            "gap_from": gap_from_iso,
                            "gap_to": gap_to_iso,
                        },
                    )
                return recovered
            except Exception as exc:  # noqa: BLE001
                if emit:
                    emit(
                        "market.feed.gap_recovery_failed",
                        {"feed_id": feed_id, "error": str(exc)[:240]},
                    )
                return 0

        set_state(FeedConnectionState.CONNECTING)
        _ = policy  # rate/circuit telemetry owned by executor wrapper

        while time.monotonic() < deadline:
            if cancelled():
                set_state(FeedConnectionState.STOPPING)
                break
            budget.raise_if_exhausted()
            set_state(
                FeedConnectionState.RECONNECTING
                if reconnect_attempt > 0
                else FeedConnectionState.CONNECTING
            )
            ws = None
            try:
                t_connect = time.perf_counter()
                ws = ws_factory(
                    ws_url,
                    open_timeout=min(10.0, max(1.0, budget.remaining())),
                    ping_interval=ping_interval,
                    ping_timeout=ping_interval,
                    close_timeout=5.0,
                )
                metrics["feed_connect_ms"] = (time.perf_counter() - t_connect) * 1000.0
                reconnect_attempt = 0
                set_state(FeedConnectionState.SYNCING)
                if last_exchange_ts and gap_recovery_enabled:
                    run_gap_recovery(last_exchange_ts, _utc_now())
                set_state(FeedConnectionState.LIVE)

                while time.monotonic() < deadline:
                    if cancelled():
                        set_state(FeedConnectionState.STOPPING)
                        break
                    try:
                        raw = ws.recv(timeout=recv_timeout)
                    except TypeError:
                        # Some fakes / older stubs use recv() without timeout kw.
                        raw = ws.recv()
                    except TimeoutError:
                        # Idle — send application ping if supported; stay LIVE.
                        if hasattr(ws, "ping"):
                            try:
                                ws.ping()
                            except Exception:  # noqa: BLE001
                                pass
                        metrics["heartbeat_count"] = int(metrics["heartbeat_count"]) + 1
                        continue
                    except Exception as recv_exc:  # noqa: BLE001
                        # Connection dropped → reconnect path
                        raise ConnectionError(str(recv_exc)) from recv_exc

                    metrics["events_received"] = int(metrics["events_received"]) + 1
                    event = normalize_binance_stream_message(
                        raw,
                        provider_id=provider_id,
                        connection_id=connection_id,
                    )
                    if event is None:
                        continue
                    if event.event_type == MarketEventType.HEARTBEAT:
                        metrics["heartbeat_count"] = int(metrics["heartbeat_count"]) + 1
                        continue
                    metrics["events_normalized"] = int(metrics["events_normalized"]) + 1
                    if event.exchange_ts:
                        last_exchange_ts = event.exchange_ts
                        metrics["last_exchange_ts"] = last_exchange_ts
                    coalesced_snapshot["last_event"] = {
                        "event_id": event.event_id,
                        "symbol": event.symbol,
                        "event_type": event.event_type.value,
                        "exchange_ts": event.exchange_ts,
                    }
                    if ingest:
                        ingest(event)
                    elif checkpoint is not None:
                        written = checkpoint.maybe_write(
                            coalesced_snapshot,
                            metrics,
                        )
                        if written:
                            metrics["checkpoint_writes"] = checkpoint.write_count
                    # Progress emit (throttled by caller / optional)
                    if emit and int(metrics["events_normalized"]) % 100 == 0:
                        emit(
                            "market.feed.progress",
                            {
                                "feed_id": feed_id,
                                "events_normalized": metrics["events_normalized"],
                                "status": state.value,
                            },
                        )
                break  # clean exit from inner loop
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001
                metrics["reconnect_count"] = int(metrics["reconnect_count"]) + 1
                reconnect_attempt += 1
                set_state(FeedConnectionState.RECONNECTING, error=str(exc)[:240])
                if cancelled() or time.monotonic() >= deadline:
                    set_state(FeedConnectionState.FAILED, error=str(exc)[:240])
                    break
                delay = min(
                    max_backoff,
                    compute_backoff_seconds(
                        reconnect_attempt - 1,
                        policy=RetryPolicy(
                            max_attempts=32,
                            base_seconds=base_backoff,
                            max_seconds=max_backoff,
                            jitter_ratio=0.25,
                        ),
                        rng=self._rng,
                    ),
                )
                if emit:
                    emit(
                        "market.feed.reconnect",
                        {
                            "feed_id": feed_id,
                            "attempt": reconnect_attempt,
                            "delay_seconds": delay,
                            "error": str(exc)[:240],
                        },
                    )
                # Sleep in small slices so cancel remains responsive.
                slept = 0.0
                while slept < delay:
                    if cancelled():
                        break
                    step = min(0.25, delay - slept)
                    self._sleep(step)
                    slept += step
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001
                        pass

        if state == FeedConnectionState.STOPPING or cancelled():
            set_state(FeedConnectionState.STOPPED)
        elif state not in {FeedConnectionState.FAILED, FeedConnectionState.STOPPED}:
            set_state(FeedConnectionState.STOPPED)

        if checkpoint is not None:
            checkpoint.maybe_write(coalesced_snapshot, metrics, force=True)
            metrics["checkpoint_writes"] = checkpoint.write_count
            metrics["checkpoint_skipped"] = checkpoint.skipped_count

        status = "cancelled" if cancelled() and state == FeedConnectionState.STOPPED else "succeeded"
        if state == FeedConnectionState.FAILED and int(metrics.get("events_normalized") or 0) == 0:
            status = "failed"

        return ProviderExecutionResult(
            status=status,
            structured={
                "feed_id": feed_id,
                "connection_id": connection_id,
                "provider_id": provider_id,
                "symbols": symbols,
                "status": state.value,
                "metrics": metrics,
                "snapshot": coalesced_snapshot,
                "ws_url_host": urlparse(ws_url).hostname,
                "truth": {
                    "market_data_only": True,
                    "live_money": "BLOCKED",
                    "not_execution": True,
                    "no_per_tick_sqlite": True,
                },
            },
            provider=provider_id,
            finish_reason="stop" if status != "failed" else "error",
            metadata={
                "capability": "market.stream",
                "events_normalized": metrics.get("events_normalized"),
                "reconnect_count": metrics.get("reconnect_count"),
                "checkpoint_writes": metrics.get("checkpoint_writes"),
            },
            error=(
                {
                    "code": "MARKET_STREAM_FAILED",
                    "message": metrics.get("error") or "stream failed",
                }
                if status == "failed"
                else None
            ),
        )
