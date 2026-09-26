"""In-process market feed runtime — domain owner for feed health + snapshots.

Long-lived WebSocket I/O runs in provider_io / market_feed workers. This runtime
consumes normalized MarketEvents, maintains bounded buffers, detects stale/gap,
and exposes snapshots to MarketSimControlPlane. It never opens network sockets.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from Data.modules.market_sim.feed.aggregator import BarAggregator, timeframe_seconds
from Data.modules.market_sim.feed.buffer import FeedBufferHub
from Data.modules.market_sim.feed.capture import FeedCaptureWriter
from Data.modules.market_sim.feed.ordering import EventOrderer
from Data.modules.market_sim.feed.types import (
    CaptureMode,
    FeedConnectionState,
    FeedMetrics,
    FeedRestartPolicy,
    FeedSubscription,
    OrderingDisposition,
)
from Data.modules.market_sim.market_event import MarketEvent, MarketEventType
from Data.modules.market_sim.types import Bar, MarketSimError


EmitFn = Callable[[str, dict[str, Any]], None]
SignalFn = Callable[[str, dict[str, Any]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FeedSession:
    def __init__(
        self,
        sub: FeedSubscription,
        *,
        emit: EmitFn | None = None,
        signal: SignalFn | None = None,
        capture: FeedCaptureWriter | None = None,
        timeframe: str = "1m",
    ) -> None:
        self.sub = sub
        self.emit = emit
        self.signal = signal
        self.capture = capture
        self.metrics = FeedMetrics()
        self.orderer = EventOrderer(max_reorder_window_ms=sub.max_reorder_window_ms)
        self.buffers = FeedBufferHub(default_capacity=sub.ring_buffer_events)
        self.aggregator = BarAggregator(timeframe=timeframe)
        self._lock = threading.RLock()
        self._last_bar_open: dict[str, str] = {}
        self._gap_unresolved: bool = False
        self._closed_bars: dict[str, list[Bar]] = {}

    def set_status(self, status: FeedConnectionState, *, error: str = "") -> None:
        with self._lock:
            prev = self.sub.status
            self.sub.status = status
            self.sub.updated_at = _utc_now()
            if error:
                self.sub.error = error
            if prev != status and self.emit:
                self.emit(
                    f"market.feed.{status.value.lower()}",
                    {
                        "feed_id": self.sub.feed_id,
                        "connection_id": self.sub.connection_id,
                        "provider_id": self.sub.provider_id,
                        "status": status.value,
                        "error": error,
                    },
                )
            if (
                prev != status
                and status in {FeedConnectionState.DEGRADED, FeedConnectionState.STALE, FeedConnectionState.LIVE}
                and self.signal
            ):
                kind = {
                    FeedConnectionState.DEGRADED: "market.feed.degraded",
                    FeedConnectionState.STALE: "market.feed.stale",
                    FeedConnectionState.LIVE: "market.feed.recovered",
                }[status]
                if status == FeedConnectionState.LIVE and prev not in {
                    FeedConnectionState.DEGRADED,
                    FeedConnectionState.STALE,
                    FeedConnectionState.SYNCING,
                    FeedConnectionState.RECONNECTING,
                }:
                    return
                self.signal(
                    kind,
                    {
                        "feed_id": self.sub.feed_id,
                        "connection_id": self.sub.connection_id,
                        "provider_id": self.sub.provider_id,
                        "symbols": list(self.sub.symbols),
                        "status": status.value,
                    },
                )

    def ingest(self, event: MarketEvent) -> dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            self.metrics.events_received += 1
            result = self.orderer.accept(event)
            if result.disposition == OrderingDisposition.DUPLICATE_DROPPED:
                self.metrics.duplicate_count += 1
                return {"accepted": False, "disposition": result.disposition.value}
            if result.disposition == OrderingDisposition.OUT_OF_WINDOW_DROPPED:
                self.metrics.dropped_count += 1
                self.metrics.out_of_order_count += 1
                return {"accepted": False, "disposition": result.disposition.value}
            if result.disposition == OrderingDisposition.LATE_ACCEPTED:
                self.metrics.late_count += 1
                self.metrics.out_of_order_count += 1
            if result.disposition == OrderingDisposition.GAP_DETECTED:
                self.metrics.gap_count += 1
                self._gap_unresolved = True
                self.set_status(FeedConnectionState.DEGRADED)
                if self.emit:
                    self.emit(
                        "market.feed.gap",
                        {
                            "feed_id": self.sub.feed_id,
                            "symbol": event.symbol,
                            "gap_from": result.gap_from,
                            "gap_to": result.gap_to,
                            "detail": result.detail,
                        },
                    )
                if self.signal:
                    self.signal(
                        "market.feed.gap",
                        {
                            "feed_id": self.sub.feed_id,
                            "symbol": event.symbol,
                            "gap_from": result.gap_from,
                            "gap_to": result.gap_to,
                        },
                    )

            accepted = result.event or event
            # Trade → aggregate bars
            derived: list[MarketEvent] = []
            if accepted.event_type == MarketEventType.TRADE and accepted.price is not None:
                derived = self.aggregator.on_trade(
                    symbol=accepted.symbol,
                    price=float(accepted.price),
                    size=accepted.size,
                    exchange_ts=accepted.exchange_ts,
                    received_at=accepted.received_at or _utc_now(),
                    available_at=accepted.available_at or accepted.received_at or _utc_now(),
                    provider_id=accepted.provider_id,
                    connection_id=accepted.connection_id,
                    provenance=accepted.provenance,
                )

            to_buffer = [accepted, *derived]
            for ev in to_buffer:
                if ev.event_type == MarketEventType.BAR_CLOSE and ev.bar and ev.bar.open_ts:
                    prev = self._last_bar_open.get(ev.symbol)
                    gap = self.orderer.detect_bar_gap(
                        ev.symbol,
                        prev_open_ts=prev,
                        next_open_ts=ev.bar.open_ts,
                        timeframe_seconds=timeframe_seconds(ev.bar.timeframe or "1m"),
                    )
                    if gap is not None:
                        self.metrics.gap_count += 1
                        self._gap_unresolved = True
                        self.set_status(FeedConnectionState.DEGRADED)
                        if self.emit:
                            self.emit(
                                "market.feed.gap",
                                {
                                    "feed_id": self.sub.feed_id,
                                    "symbol": ev.symbol,
                                    "detail": gap.detail,
                                },
                            )
                    self._last_bar_open[ev.symbol] = ev.bar.open_ts
                    self._closed_bars.setdefault(ev.symbol, []).append(
                        Bar(
                            ts=ev.bar.open_ts,
                            open=float(ev.bar.open or 0),
                            high=float(ev.bar.high or 0),
                            low=float(ev.bar.low or 0),
                            close=float(ev.bar.close or 0),
                            volume=float(ev.bar.volume or 0),
                        )
                    )
                coalesced = self.buffers.buffer(ev.symbol).push(ev)
                if coalesced is not None:
                    self.metrics.coalesced_count += 1
                if self.capture:
                    self.capture.write(self.sub.feed_id, ev)

            now = _utc_now()
            self.sub.last_event_at = now
            self.sub.last_received_at = accepted.received_at or now
            if accepted.exchange_ts:
                self.sub.last_exchange_ts = accepted.exchange_ts
            self.sub.updated_at = now
            self.metrics.events_accepted += 1
            ingest_ms = (time.perf_counter() - t0) * 1000.0
            self.metrics.market_ingest_latency_ms = ingest_ms
            self.metrics.observe_latency(ingest_ms)
            if self.sub.status in {
                FeedConnectionState.CONNECTING,
                FeedConnectionState.SYNCING,
                FeedConnectionState.RECONNECTING,
            }:
                self.set_status(FeedConnectionState.LIVE)
            return {
                "accepted": True,
                "disposition": result.disposition.value,
                "derived": len(derived),
            }

    def begin_reconnect(self, *, reason: str = "transport_reconnect") -> dict[str, Any]:
        """Mark transport reconnect without clearing EventOrderer seen_ids (T09).

        Replay after reconnect must keep dropping duplicate event_id values so
        downstream paper fills cannot double-apply the same trade.
        """
        with self._lock:
            self.metrics.reconnect_count += 1
            self.sub.connection_id = f"conn_{uuid.uuid4().hex[:10]}"
            self.sub.error = reason
            self.sub.updated_at = _utc_now()
            self.set_status(FeedConnectionState.RECONNECTING, error=reason)
            return {
                "feed_id": self.sub.feed_id,
                "connection_id": self.sub.connection_id,
                "reconnect_count": self.metrics.reconnect_count,
                "orderer_symbols": list(self.orderer._states.keys()),
                "truth": {
                    "seen_ids_preserved": True,
                    "no_duplicate_paper_fill_on_replay": True,
                },
            }

    def mark_recovered(self) -> None:
        with self._lock:
            self._gap_unresolved = False
            if self.sub.status in {
                FeedConnectionState.DEGRADED,
                FeedConnectionState.RECONNECTING,
            }:
                self.set_status(FeedConnectionState.LIVE)

    def check_stale(self, *, now: float | None = None) -> bool:
        with self._lock:
            if self.sub.status in {
                FeedConnectionState.STOPPED,
                FeedConnectionState.STOPPING,
                FeedConnectionState.DISCONNECTED,
                FeedConnectionState.FAILED,
            }:
                return False
            if not self.sub.last_received_at:
                return False
            try:
                last = datetime.fromisoformat(self.sub.last_received_at.replace("Z", "+00:00"))
            except ValueError:
                return False
            now_dt = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
            stale_ms = (now_dt - last.astimezone(timezone.utc)).total_seconds() * 1000.0
            self.metrics.feed_staleness_ms = stale_ms
            if stale_ms > self.sub.stale_after_seconds * 1000.0:
                if self.sub.status != FeedConnectionState.STALE:
                    self.set_status(FeedConnectionState.STALE)
                return True
            return False

    def health(self) -> dict[str, Any]:
        with self._lock:
            self.check_stale()
            return {
                "feed_id": self.sub.feed_id,
                "status": self.sub.status.value,
                "gap_unresolved": self._gap_unresolved,
                "allows_new_risk": self.allows_new_risk(),
                "staleness_ms": self.metrics.feed_staleness_ms,
                "metrics": self.metrics.public_dict(),
            }

    def allows_new_risk(self) -> bool:
        if self._gap_unresolved:
            return False
        if self.sub.status in {
            FeedConnectionState.STALE,
            FeedConnectionState.FAILED,
            FeedConnectionState.DISCONNECTED,
            FeedConnectionState.DEGRADED,
            FeedConnectionState.STOPPED,
            FeedConnectionState.STOPPING,
        }:
            return False
        return self.sub.status in {
            FeedConnectionState.LIVE,
            FeedConnectionState.SYNCING,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self.check_stale()
            symbols: dict[str, Any] = {}
            for sym in self.sub.symbols:
                buf = self.buffers.buffer(sym)
                last_trade = buf.latest_of_type(MarketEventType.TRADE)
                last_quote = buf.latest_of_type(MarketEventType.QUOTE)
                last_close = buf.latest_of_type(MarketEventType.BAR_CLOSE)
                building = self.aggregator.building(sym)
                ord_state = self.orderer.state_for(sym)
                symbols[sym] = {
                    "last_trade": last_trade.public_dict() if last_trade else None,
                    "last_quote": last_quote.public_dict() if last_quote else None,
                    "last_closed_bar": last_close.public_dict() if last_close else None,
                    "building_bar": building.to_payload().public_dict() if building else None,
                    "sequence_last": ord_state.last_sequence,
                    "duplicate_count": ord_state.duplicate_count,
                    "gap_count": ord_state.gap_count,
                    "buffer": buf.snapshot(),
                    "closed_bar_count": len(self._closed_bars.get(sym, [])),
                }
            return {
                "subscription": self.sub.public_dict(),
                "health": self.health(),
                "symbols": symbols,
                "metrics": self.metrics.public_dict(),
            }

    def closed_bars(self, symbol: str) -> list[Bar]:
        with self._lock:
            return list(self._closed_bars.get(symbol, []))


class FeedRuntime:
    """Process-local registry of feed sessions (domain state, not network)."""

    def __init__(
        self,
        *,
        emit: EmitFn | None = None,
        signal: SignalFn | None = None,
        capture_root: Any | None = None,
        artifact_store: Any | None = None,
    ) -> None:
        self.emit = emit
        self.signal = signal
        self.capture_root = capture_root
        self.artifact_store = artifact_store
        self._sessions: dict[str, FeedSession] = {}
        self._lock = threading.RLock()

    def create_subscription(
        self,
        *,
        provider_id: str,
        symbols: list[str],
        stream_kinds: list[str] | None = None,
        restart_policy: str = "MANUAL",
        capture_mode: str = "OFF",
        stale_after_seconds: float = 30.0,
        max_reorder_window_ms: float = 2000.0,
        ring_buffer_events: int = 1024,
        gap_recovery_enabled: bool = True,
        feed_id: str | None = None,
        license_note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> FeedSession:
        fid = feed_id or f"feed_{uuid.uuid4().hex[:12]}"
        with self._lock:
            if fid in self._sessions:
                raise MarketSimError("FEED_EXISTS", fid, http_status=409)
            sub = FeedSubscription(
                feed_id=fid,
                provider_id=provider_id,
                symbols=[s.upper() for s in symbols],
                stream_kinds=list(stream_kinds or ["kline_1m"]),
                restart_policy=FeedRestartPolicy(restart_policy),
                capture_mode=CaptureMode(capture_mode),
                stale_after_seconds=stale_after_seconds,
                max_reorder_window_ms=max_reorder_window_ms,
                ring_buffer_events=ring_buffer_events,
                gap_recovery_enabled=gap_recovery_enabled,
                connection_id=f"conn_{uuid.uuid4().hex[:10]}",
                status=FeedConnectionState.DISCONNECTED,
                license_state="PUBLIC_TERMS_APPLY",
                license_note=license_note,
                created_at=_utc_now(),
                updated_at=_utc_now(),
                metadata=dict(metadata or {}),
            )
            capture = None
            if sub.capture_mode != CaptureMode.OFF and self.capture_root is not None:
                capture = FeedCaptureWriter(
                    self.capture_root,
                    mode=sub.capture_mode,
                    artifact_store=self.artifact_store,
                )
            session = FeedSession(
                sub,
                emit=self.emit,
                signal=self.signal,
                capture=capture,
            )
            self._sessions[fid] = session
            return session

    def get(self, feed_id: str) -> FeedSession:
        with self._lock:
            if feed_id not in self._sessions:
                raise MarketSimError("FEED_NOT_FOUND", feed_id, http_status=404)
            return self._sessions[feed_id]

    def list_feeds(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.sub.public_dict() for s in self._sessions.values()]

    def stop(self, feed_id: str) -> dict[str, Any]:
        session = self.get(feed_id)
        session.set_status(FeedConnectionState.STOPPING)
        if session.capture:
            session.capture.close_all()
        session.set_status(FeedConnectionState.STOPPED)
        return session.sub.public_dict()

    def ingest(self, feed_id: str, event: MarketEvent) -> dict[str, Any]:
        return self.get(feed_id).ingest(event)

    def snapshot(self, feed_id: str) -> dict[str, Any]:
        return self.get(feed_id).snapshot()

    def durable_checkpoint(self, feed_id: str) -> dict[str, Any]:
        """Small CONTROL_WRITE-sized checkpoint (not raw ticks)."""
        session = self.get(feed_id)
        snap = session.snapshot()
        return {
            "feed_id": feed_id,
            "connection_id": session.sub.connection_id,
            "status": session.sub.status.value,
            "symbols": list(session.sub.symbols),
            "restart_policy": session.sub.restart_policy.value,
            "last_received_at": session.sub.last_received_at,
            "last_exchange_ts": session.sub.last_exchange_ts,
            "gap_unresolved": snap["health"]["gap_unresolved"],
            "metrics_summary": {
                "events_received": session.metrics.events_received,
                "duplicate_count": session.metrics.duplicate_count,
                "gap_count": session.metrics.gap_count,
                "reconnect_count": session.metrics.reconnect_count,
            },
            "updated_at": _utc_now(),
        }
