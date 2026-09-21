"""Control-plane event bus for settings/policy changes."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable


Listener = Callable[[dict[str, Any]], None]


class ControlEventBus:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._history: list[dict[str, Any]] = []
        self._history_limit = 500

    def subscribe(self, event_type: str, listener: Listener) -> None:
        with self._lock:
            self._listeners[event_type].append(listener)

    def unsubscribe(self, event_type: str, listener: Listener) -> None:
        with self._lock:
            listeners = self._listeners.get(event_type, [])
            self._listeners[event_type] = [item for item in listeners if item is not listener]

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {"type": event_type, **(payload or {})}
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit :]
            listeners = list(self._listeners.get(event_type, []))
            listeners += list(self._listeners.get("*", []))
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Subscribers must not break configuration updates.
                continue
        return event

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history[-limit:])


control_events = ControlEventBus()
