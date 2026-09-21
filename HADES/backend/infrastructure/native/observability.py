"""Native observability counters exposed to diagnostics / Mission Control.

Bounded in-process counters — not an unbounded telemetry sink.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NativeObsSnapshot:
    rpc_calls: int = 0
    rpc_failures: int = 0
    rpc_timeouts: int = 0
    rpc_cancellations: int = 0
    native_restarts: int = 0
    native_crashes: int = 0
    last_queue_ms: float | None = None
    last_duration_ms: float | None = None
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rpc_calls": self.rpc_calls,
            "rpc_failures": self.rpc_failures,
            "rpc_timeouts": self.rpc_timeouts,
            "rpc_cancellations": self.rpc_cancellations,
            "native_restarts": self.native_restarts,
            "native_crashes": self.native_crashes,
            "last_queue_ms": self.last_queue_ms,
            "last_duration_ms": self.last_duration_ms,
            "updated_at": self.updated_at,
        }


class NativeObservability:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap = NativeObsSnapshot()

    def record_rpc(self, *, ok: bool, queue_ms: float | None = None, duration_ms: float | None = None) -> None:
        with self._lock:
            self._snap.rpc_calls += 1
            if not ok:
                self._snap.rpc_failures += 1
            if queue_ms is not None:
                self._snap.last_queue_ms = queue_ms
            if duration_ms is not None:
                self._snap.last_duration_ms = duration_ms
            self._snap.updated_at = time.time()

    def record_timeout(self) -> None:
        with self._lock:
            self._snap.rpc_timeouts += 1
            self._snap.updated_at = time.time()

    def record_cancel(self) -> None:
        with self._lock:
            self._snap.rpc_cancellations += 1
            self._snap.updated_at = time.time()

    def record_restart(self) -> None:
        with self._lock:
            self._snap.native_restarts += 1
            self._snap.updated_at = time.time()

    def record_crash(self) -> None:
        with self._lock:
            self._snap.native_crashes += 1
            self._snap.updated_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snap.as_dict()


_obs = NativeObservability()


def get_native_observability() -> NativeObservability:
    return _obs
