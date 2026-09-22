"""Bounded in-memory time-series for performance metrics."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricSample:
    ts_ms: float
    value: float
    labels: tuple[tuple[str, str], ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "value": self.value,
            "labels": dict(self.labels),
        }


class TimeSeriesStore:
    """Process-local time series with retention and percentile helpers."""

    def __init__(self, *, max_points_per_series: int = 3_600) -> None:
        if max_points_per_series < 10:
            raise ValueError("max_points_per_series must be >= 10")
        self.max_points = max_points_per_series
        self._series: dict[str, deque[MetricSample]] = defaultdict(
            lambda: deque(maxlen=self.max_points)
        )
        self._lock = threading.RLock()
        # Rolling latency buffers for percentile math
        self._latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=2_000))

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        sample = MetricSample(
            ts_ms=time.time() * 1000,
            value=float(value),
            labels=tuple(sorted((labels or {}).items())),
        )
        with self._lock:
            self._series[name].append(sample)

    def observe_latency_ms(self, name: str, duration_ms: float) -> None:
        duration_ms = float(duration_ms)
        self.observe(f"{name}.latency_ms", duration_ms)
        with self._lock:
            self._latencies[name].append(duration_ms)

    def range(
        self,
        name: str,
        *,
        since_ms: float | None = None,
        until_ms: float | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 5_000))
        with self._lock:
            items = list(self._series.get(name, ()))
        if since_ms is not None:
            items = [i for i in items if i.ts_ms >= since_ms]
        if until_ms is not None:
            items = [i for i in items if i.ts_ms <= until_ms]
        return [i.public_dict() for i in items[-limit:]]

    def percentiles(self, name: str) -> dict[str, float | None]:
        with self._lock:
            values = list(self._latencies.get(name, ()))
        if not values:
            return {"p50": None, "p95": None, "p99": None, "count": 0, "avg": None}
        ordered = sorted(values)
        return {
            "p50": _percentile(ordered, 50),
            "p95": _percentile(ordered, 95),
            "p99": _percentile(ordered, 99),
            "count": len(ordered),
            "avg": sum(ordered) / len(ordered),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            series_names = sorted(self._series.keys())
            latency_names = sorted(self._latencies.keys())
        return {
            "series": series_names,
            "latency_tracks": latency_names,
            "max_points_per_series": self.max_points,
            "truth": {
                "in_process_only": True,
                "missing_sample_is_not_zero": True,
            },
        }

    def hot_paths(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with self._lock:
            for name, values in self._latencies.items():
                if not values:
                    continue
                ordered = sorted(values)
                rows.append(
                    {
                        "name": name,
                        "count": len(ordered),
                        "avg_ms": sum(ordered) / len(ordered),
                        "p50_ms": _percentile(ordered, 50),
                        "p95_ms": _percentile(ordered, 95),
                        "p99_ms": _percentile(ordered, 99),
                    }
                )
        rows.sort(key=lambda r: (-r["count"], -r["p95_ms"]))
        return rows[: max(1, min(limit, 100))]


def _percentile(ordered: list[float], pct: float) -> float:
    if not ordered:
        return math.nan
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight
