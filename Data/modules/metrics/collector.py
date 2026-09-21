from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class MetricsSnapshot:
    collected_at: float
    counters: dict[str, int]
    gauges: dict[str, float]
    labels: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "collected_at": self.collected_at,
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "labels": dict(self.labels),
            "truth": {
                "metrics_are_not_apm": True,
                "in_process_only": True,
            },
        }


class MetricsCollector:
    """Simple process-local counters and gauges for /api/metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._started_at = time.time()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = float(value)

    def snapshot(
        self,
        *,
        labels: dict[str, str] | None = None,
        enrich: Callable[[], dict[str, float]] | None = None,
    ) -> MetricsSnapshot:
        with self._lock:
            gauges = dict(self._gauges)
            counters = dict(self._counters)
        gauges["uptime_seconds"] = max(0.0, time.time() - self._started_at)
        if enrich:
            gauges.update(enrich())
        return MetricsSnapshot(
            collected_at=time.time(),
            counters=counters,
            gauges=gauges,
            labels=labels or {},
        )
