"""Per-key single-flight coalescing for safe deterministic work.

Leader computation runs outside the map lock. Waiter cancellation does not
cancel the leader. Leader failure wakes waiters with a truthful error.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Flight(Generic[T]):
    event: threading.Event = field(default_factory=threading.Event)
    result: T | None = None
    error: BaseException | None = None
    waiters: int = 0
    started_at: float = field(default_factory=time.monotonic)


class SingleFlight(Generic[T]):
    """Coalesce identical in-flight computations by key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, _Flight[T]] = {}
        self._stats = {
            "lookups": 0,
            "leaders": 0,
            "waits": 0,
            "hits_joined": 0,
            "failures": 0,
        }

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def do(self, key: str, fn: Callable[[], T]) -> T:
        """Run fn as leader or wait for an in-flight leader for the same key."""
        with self._lock:
            self._stats["lookups"] += 1
            existing = self._inflight.get(key)
            if existing is not None:
                existing.waiters += 1
                self._stats["waits"] += 1
                flight = existing
                is_leader = False
            else:
                flight = _Flight()
                self._inflight[key] = flight
                self._stats["leaders"] += 1
                is_leader = True

        if is_leader:
            try:
                result = fn()
                flight.result = result
                return result
            except BaseException as exc:  # noqa: BLE001 — propagate after waking waiters
                flight.error = exc
                self._stats["failures"] += 1
                raise
            finally:
                flight.event.set()
                with self._lock:
                    self._inflight.pop(key, None)
        else:
            flight.event.wait()
            with self._lock:
                self._stats["hits_joined"] += 1
            if flight.error is not None:
                raise flight.error
            return flight.result  # type: ignore[return-value]
