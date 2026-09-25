"""Market feed domain types — connection/health/capture contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FeedConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    SYNCING = "SYNCING"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    RECONNECTING = "RECONNECTING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class FeedRestartPolicy(str, Enum):
    AUTO_RESUME = "AUTO_RESUME"
    MANUAL = "MANUAL"
    DISABLED = "DISABLED"


class CaptureMode(str, Enum):
    OFF = "OFF"
    BAR_ONLY = "BAR_ONLY"
    RAW_SEGMENTED = "RAW_SEGMENTED"


class OrderingDisposition(str, Enum):
    ORDERED = "ORDERED"
    LATE_ACCEPTED = "LATE_ACCEPTED"
    DUPLICATE_DROPPED = "DUPLICATE_DROPPED"
    GAP_DETECTED = "GAP_DETECTED"
    OUT_OF_WINDOW_DROPPED = "OUT_OF_WINDOW_DROPPED"


@dataclass
class FeedMetrics:
    events_received: int = 0
    events_accepted: int = 0
    duplicate_count: int = 0
    out_of_order_count: int = 0
    gap_count: int = 0
    late_count: int = 0
    dropped_count: int = 0
    coalesced_count: int = 0
    reconnect_count: int = 0
    feed_connect_ms: float | None = None
    feed_staleness_ms: float | None = None
    market_ingest_latency_ms: float | None = None
    normalization_ms: float | None = None
    bar_aggregation_ms: float | None = None
    latency_samples_ms: list[float] = field(default_factory=list)

    def observe_latency(self, ms: float, *, max_samples: int = 2048) -> None:
        self.latency_samples_ms.append(float(ms))
        if len(self.latency_samples_ms) > max_samples:
            self.latency_samples_ms = self.latency_samples_ms[-max_samples:]

    def latency_stats(self) -> dict[str, Any]:
        samples = sorted(self.latency_samples_ms)
        n = len(samples)
        if n == 0:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "mean": None,
                "p50": None,
                "p95": None,
                "p99": None,
                "status": "UNMEASURED",
            }
        def pct(p: float) -> float:
            if n < 2 and p > 50:
                return samples[-1]
            idx = min(n - 1, max(0, int(round((p / 100.0) * (n - 1)))))
            return samples[idx]

        mean = sum(samples) / n
        out = {
            "count": n,
            "min": samples[0],
            "max": samples[-1],
            "mean": mean,
            "p50": pct(50),
            "p95": pct(95) if n >= 20 else None,
            "p99": pct(99) if n >= 100 else None,
            "status": "MEASURED" if n >= 20 else "INSUFFICIENT_SAMPLE",
        }
        return out

    def public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("latency_samples_ms", None)
        d["latency"] = self.latency_stats()
        return d


@dataclass
class FeedSubscription:
    feed_id: str
    provider_id: str
    symbols: list[str]
    stream_kinds: list[str] = field(default_factory=lambda: ["kline_1m", "trade"])
    restart_policy: FeedRestartPolicy = FeedRestartPolicy.MANUAL
    capture_mode: CaptureMode = CaptureMode.OFF
    stale_after_seconds: float = 30.0
    max_reorder_window_ms: float = 2000.0
    ring_buffer_events: int = 1024
    gap_recovery_enabled: bool = True
    connection_id: str = ""
    job_id: str | None = None
    status: FeedConnectionState = FeedConnectionState.DISCONNECTED
    license_state: str = "PUBLIC_TERMS_APPLY"
    license_note: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_event_at: str | None = None
    last_exchange_ts: str | None = None
    last_received_at: str | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "provider_id": self.provider_id,
            "symbols": list(self.symbols),
            "stream_kinds": list(self.stream_kinds),
            "restart_policy": self.restart_policy.value,
            "capture_mode": self.capture_mode.value,
            "stale_after_seconds": self.stale_after_seconds,
            "max_reorder_window_ms": self.max_reorder_window_ms,
            "ring_buffer_events": self.ring_buffer_events,
            "gap_recovery_enabled": self.gap_recovery_enabled,
            "connection_id": self.connection_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "license_state": self.license_state,
            "license_note": self.license_note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_event_at": self.last_event_at,
            "last_exchange_ts": self.last_exchange_ts,
            "last_received_at": self.last_received_at,
            "error": self.error,
            "metadata": dict(self.metadata),
            "truth": {
                "market_data_only": True,
                "live_money": "BLOCKED",
                "not_execution": True,
            },
        }
