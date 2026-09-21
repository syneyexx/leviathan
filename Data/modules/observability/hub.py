from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    category: str
    name: str
    created_at_ms: float
    payload: dict[str, Any] = field(default_factory=dict)
    level: str = "info"

    def public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category,
            "name": self.name,
            "created_at_ms": self.created_at_ms,
            "payload": self.payload,
            "level": self.level,
        }


class ObservabilityHub:
    """In-process telemetry ring buffer + counters. Not a full APM product."""

    def __init__(self, *, capacity: int = 500) -> None:
        if capacity < 10:
            raise ValueError("capacity must be >= 10")
        self.capacity = capacity
        self._events: deque[TelemetryEvent] = deque(maxlen=capacity)
        self._lock = threading.RLock()
        self.counters: dict[str, int] = {}

    def emit(
        self,
        category: str,
        name: str,
        *,
        payload: dict[str, Any] | None = None,
        level: str = "info",
    ) -> TelemetryEvent:
        event = TelemetryEvent(
            event_id=str(uuid.uuid4()),
            category=category,
            name=name,
            created_at_ms=time.time() * 1000,
            payload=payload or {},
            level=level,
        )
        key = f"{category}.{name}"
        with self._lock:
            self._events.append(event)
            self.counters[key] = self.counters.get(key, 0) + 1
        return event

    def recent(self, *, limit: int = 50, category: str | None = None) -> list[TelemetryEvent]:
        with self._lock:
            items = list(self._events)
        if category:
            items = [item for item in items if item.category == category]
        return list(reversed(items[-max(1, min(limit, self.capacity)) :]))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "capacity": self.capacity,
                "buffered": len(self._events),
                "counters": dict(sorted(self.counters.items())),
            }
