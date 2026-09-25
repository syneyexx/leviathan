"""Bounded per-symbol ring buffers with coalescing for market feed backpressure."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from Data.modules.market_sim.market_event import MarketEvent, MarketEventType


@dataclass
class BufferStats:
    accepted: int = 0
    dropped: int = 0
    coalesced: int = 0


class SymbolRingBuffer:
    """Bounded ring buffer. BAR_UPDATE may coalesce; BAR_CLOSE must not silently vanish."""

    def __init__(self, capacity: int = 1024) -> None:
        self.capacity = max(8, int(capacity))
        self._events: deque[MarketEvent] = deque()
        self.stats = BufferStats()
        self._building_bar: MarketEvent | None = None

    def __len__(self) -> int:
        return len(self._events)

    def push(self, event: MarketEvent) -> MarketEvent | None:
        """Push event; return coalesced-away event if any (for metrics)."""
        if event.event_type == MarketEventType.BAR_UPDATE:
            if self._building_bar is not None:
                self.stats.coalesced += 1
                coalesced = self._building_bar
                self._building_bar = event
                # Replace last BAR_UPDATE in deque if present.
                for i in range(len(self._events) - 1, -1, -1):
                    if self._events[i].event_type == MarketEventType.BAR_UPDATE:
                        self._events[i] = event
                        self.stats.accepted += 1
                        return coalesced
                self._events.append(event)
                self.stats.accepted += 1
                self._trim()
                return coalesced
            self._building_bar = event
            self._events.append(event)
            self.stats.accepted += 1
            self._trim()
            return None

        if event.event_type == MarketEventType.BAR_CLOSE:
            self._building_bar = None

        if len(self._events) >= self.capacity:
            # Prefer dropping HEARTBEAT / BAR_UPDATE over BAR_CLOSE / TRADE / GAP / STATUS.
            dropped = self._drop_lowest_priority()
            if dropped is None:
                # Hard drop oldest non-critical if still full.
                for i, ev in enumerate(self._events):
                    if ev.event_type in {MarketEventType.HEARTBEAT, MarketEventType.BAR_UPDATE}:
                        dropped = self._events[i]
                        del self._events[i]
                        break
                if dropped is None:
                    dropped = self._events.popleft()
            self.stats.dropped += 1
        self._events.append(event)
        self.stats.accepted += 1
        return None

    def _drop_lowest_priority(self) -> MarketEvent | None:
        for i, ev in enumerate(self._events):
            if ev.event_type in {MarketEventType.HEARTBEAT, MarketEventType.BAR_UPDATE}:
                out = self._events[i]
                del self._events[i]
                return out
        return None

    def _trim(self) -> None:
        while len(self._events) > self.capacity:
            dropped = self._drop_lowest_priority()
            if dropped is None:
                self._events.popleft()
            self.stats.dropped += 1

    def latest(self, n: int = 1) -> list[MarketEvent]:
        if n <= 0:
            return []
        items = list(self._events)
        return items[-n:]

    def latest_of_type(self, event_type: MarketEventType) -> MarketEvent | None:
        for ev in reversed(self._events):
            if ev.event_type == event_type:
                return ev
        return None

    def snapshot(self) -> dict[str, Any]:
        last = self._events[-1] if self._events else None
        return {
            "size": len(self._events),
            "capacity": self.capacity,
            "stats": {
                "accepted": self.stats.accepted,
                "dropped": self.stats.dropped,
                "coalesced": self.stats.coalesced,
            },
            "last_event_id": last.event_id if last else None,
            "last_event_type": last.event_type.value if last else None,
        }


class FeedBufferHub:
    def __init__(self, *, default_capacity: int = 1024) -> None:
        self.default_capacity = default_capacity
        self._buffers: dict[str, SymbolRingBuffer] = {}

    def buffer(self, symbol: str) -> SymbolRingBuffer:
        if symbol not in self._buffers:
            self._buffers[symbol] = SymbolRingBuffer(self.default_capacity)
        return self._buffers[symbol]

    def push(self, event: MarketEvent) -> None:
        self.buffer(event.symbol).push(event)

    def public_dict(self) -> dict[str, Any]:
        return {sym: buf.snapshot() for sym, buf in self._buffers.items()}
