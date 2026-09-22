"""In-process SSE fan-out for observability events."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class _Subscriber:
    subscriber_id: str
    queue: asyncio.Queue[dict[str, Any] | None]
    created_at: float = field(default_factory=time.time)
    dropped: int = 0


class EventStreamBroker:
    """Fan-out broker with bounded per-subscriber queues and backpressure."""

    def __init__(
        self,
        *,
        max_subscribers: int = 64,
        queue_size: int = 256,
    ) -> None:
        self.max_subscribers = max(1, max_subscribers)
        self.queue_size = max(8, queue_size)
        self._lock = threading.RLock()
        self._subscribers: dict[str, _Subscriber] = {}
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        """Publish from any thread; drop oldest for slow subscribers."""
        with self._lock:
            dead: list[str] = []
            for sid, sub in self._subscribers.items():
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        _ = sub.queue.get_nowait()
                        sub.dropped += 1
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        sub.queue.put_nowait(event)
                    except asyncio.QueueFull:
                        sub.dropped += 1
                except Exception:
                    dead.append(sid)
            for sid in dead:
                self._subscribers.pop(sid, None)

    def subscribe(self, subscriber_id: str | None = None) -> _Subscriber:
        import uuid

        sid = subscriber_id or str(uuid.uuid4())
        with self._lock:
            if len(self._subscribers) >= self.max_subscribers:
                # Evict oldest
                oldest = min(self._subscribers.values(), key=lambda s: s.created_at)
                self._subscribers.pop(oldest.subscriber_id, None)
                try:
                    oldest.queue.put_nowait(None)
                except Exception:
                    pass
            sub = _Subscriber(
                subscriber_id=sid,
                queue=asyncio.Queue(maxsize=self.queue_size),
            )
            self._subscribers[sid] = sub
            return sub

    def unsubscribe(self, subscriber_id: str) -> None:
        with self._lock:
            sub = self._subscribers.pop(subscriber_id, None)
        if sub is not None:
            try:
                sub.queue.put_nowait(None)
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._lock:
            subs = list(self._subscribers.values())
            self._subscribers.clear()
        for sub in subs:
            try:
                sub.queue.put_nowait(None)
            except Exception:
                pass

    async def stream(
        self,
        *,
        subscriber_id: str | None = None,
        heartbeat_seconds: float = 15.0,
    ) -> AsyncIterator[str]:
        """Yield SSE-encoded strings until unsubscribe/shutdown."""
        sub = self.subscribe(subscriber_id)
        try:
            yield _sse("connected", {"subscriber_id": sub.subscriber_id, "ts": time.time()})
            while True:
                try:
                    item = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield _sse("heartbeat", {"ts": time.time(), "dropped": sub.dropped})
                    continue
                if item is None:
                    yield _sse("closed", {"reason": "shutdown"})
                    break
                seq = item.get("sequence")
                yield _sse("event", item, event_id=str(seq) if seq is not None else None)
        finally:
            self.unsubscribe(sub.subscriber_id)


def _sse(event: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.append(f"data: {payload}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# Small ring used when no durable store backfill is available for tests.
class RecentRing:
    def __init__(self, capacity: int = 200) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def push(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(item)

    def after(self, sequence: int, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            items = [i for i in self._items if int(i.get("sequence") or 0) > sequence]
        return items[:limit]
