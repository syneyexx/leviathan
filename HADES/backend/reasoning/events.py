"""Shared run event protocol for Chat, Tasks and Research progress."""

from __future__ import annotations

import asyncio
import json
import time
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal
from uuid import uuid4


EventType = Literal[
    "request_received",
    "route_chosen",
    "step_started",
    "step_completed",
    "source_acquired",
    "tool_status",
    "replan",
    "verification",
    "waiting_for_input",
    "stream_delta",
    "final_outcome",
    "error",
    "cancelled",
    "paused",
    "resumed",
    # HADES-10 conversation timeline cards (payload carries engine-specific detail)
    "coding_status",
    "research_status",
    "work_status",
    "approval_status",
    "artifact_status",
]


@dataclass(slots=True)
class RunEvent:
    event_id: str
    run_id: str
    type: EventType
    timestamp: float
    sequence: int
    payload: dict[str, Any] = field(default_factory=dict)
    provisional: bool = False  # True for draft/stream text not yet verified

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_sse(self) -> str:
        return f"id: {self.event_id}\ndata: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"


Subscriber = tuple[asyncio.Queue[RunEvent | None], asyncio.AbstractEventLoop]


TERMINAL_EVENT_TYPES = {"final_outcome", "error", "cancelled"}
DEFAULT_TERMINAL_GRACE_S = 90.0
DEFAULT_COMPACT_KEEP = 8


class RunEventBus:
    """In-memory event log + subscriber fan-out with reconnect by sequence."""

    def __init__(
        self,
        *,
        maxlen: int | None = None,
        terminal_grace_s: float = DEFAULT_TERMINAL_GRACE_S,
        compact_keep: int = DEFAULT_COMPACT_KEEP,
    ) -> None:
        self._maxlen_override = maxlen
        self._terminal_grace_s = max(1.0, float(terminal_grace_s))
        self._compact_keep = max(1, int(compact_keep))
        self._events: dict[str, list[RunEvent]] = {}
        self._seq: dict[str, int] = {}
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._thread_lock = threading.Lock()
        self._loop_locks: dict[int, asyncio.Lock] = {}
        self._durable_sink: Callable[[RunEvent], None] | None = None
        self._sequence_bootstrap: Callable[[str], int] | None = None
        self._terminal_at: dict[str, float] = {}
        self._evicted: int = 0

    @property
    def maxlen(self) -> int:
        if self._maxlen_override is not None:
            return max(10, int(self._maxlen_override))
        try:
            from control.service import resolve_setting

            value = resolve_setting("runtime.event_buffer_maxlen", default=2000)
            if value is None:
                return 10_000_000
            return max(10, int(value))
        except Exception:
            return 2000

    @maxlen.setter
    def maxlen(self, value: int) -> None:
        self._maxlen_override = int(value)

    def set_durable_sink(self, sink: Callable[[RunEvent], None] | None) -> None:
        """Optional Gen2 Flight Recorder hook (must be sync and fail-soft)."""
        self._durable_sink = sink

    def set_sequence_bootstrap(self, bootstrap: Callable[[str], int] | None) -> None:
        """Return the highest durable sequence for a run_id (0 if none). Used after restart."""
        self._sequence_bootstrap = bootstrap

    def _persist(self, event: RunEvent) -> None:
        sink = self._durable_sink
        if sink is None or event.provisional:
            return
        try:
            sink(event)
        except Exception:
            # Flight recorder must never break live orchestration.
            pass

    def stats(self) -> dict[str, int]:
        with self._thread_lock:
            events = sum(len(bucket) for bucket in self._events.values())
            return {
                "runs": len(self._events),
                "events": events,
                "subscribers": sum(len(items) for items in self._subscribers.values()),
                "evicted_runs": self._evicted,
                "terminal_pending": len(self._terminal_at),
            }

    def _remember_terminal(self, event: RunEvent) -> None:
        if event.type in TERMINAL_EVENT_TYPES:
            self._terminal_at[event.run_id] = time.time()

    def reap(self, *, now: float | None = None, force: bool = False) -> int:
        """Drop detailed in-memory history for terminal runs after the reconnect grace period."""
        now = time.time() if now is None else now
        removed = 0
        with self._thread_lock:
            for run_id, closed_at in list(self._terminal_at.items()):
                if not force and (now - closed_at) < self._terminal_grace_s:
                    continue
                if self._subscribers.get(run_id):
                    continue
                bucket = self._events.get(run_id) or []
                kept = [event for event in bucket if event.type in TERMINAL_EVENT_TYPES]
                durable = [event for event in bucket if not event.provisional and event.type not in TERMINAL_EVENT_TYPES]
                compact = durable[-self._compact_keep :] + kept
                # Deduplicate while preserving order.
                seen: set[str] = set()
                ordered: list[RunEvent] = []
                for event in compact:
                    if event.event_id in seen:
                        continue
                    seen.add(event.event_id)
                    ordered.append(event)
                if ordered:
                    self._events[run_id] = ordered
                else:
                    self._events.pop(run_id, None)
                self._terminal_at.pop(run_id, None)
                self._evicted += 1
                removed += 1
        return removed

    def _async_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = self._loop_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._loop_locks[key] = lock
        return lock

    def _next_seq(self, run_id: str) -> int:
        if run_id not in self._seq:
            base = 0
            bootstrap = self._sequence_bootstrap
            if bootstrap is not None:
                try:
                    base = max(0, int(bootstrap(run_id)))
                except Exception:
                    base = 0
            self._seq[run_id] = base
        self._seq[run_id] = self._seq.get(run_id, 0) + 1
        return self._seq[run_id]

    @staticmethod
    def _queue_event(queue: asyncio.Queue[RunEvent | None], event: RunEvent, resync_on_full: bool) -> None:
        """Put on a queue from its owning event-loop thread."""
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            if not resync_on_full:
                return

        try:
            # Explicit resync signal — do not silently drop terminal progress.
            marker = RunEvent(
                event_id=f"evt_{uuid4().hex[:12]}",
                run_id=event.run_id,
                type="error",
                timestamp=time.time(),
                sequence=event.sequence,
                payload={
                    "resync_required": True,
                    "reason": "subscriber_queue_full",
                    "missed_event_id": event.event_id,
                },
                provisional=True,
            )
            # Best-effort: drop oldest then signal.
            try:
                queue.get_nowait()
            except Exception:
                pass
            queue.put_nowait(marker)
        except Exception:
            pass

    def _fan_out(self, subscribers: list[Subscriber], event: RunEvent, *, resync_on_full: bool) -> None:
        """Deliver on each subscriber's owning loop; safe from worker threads."""
        try:
            current_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        for queue, owner_loop in subscribers:
            if owner_loop.is_closed():
                continue
            if owner_loop is current_loop:
                self._queue_event(queue, event, resync_on_full)
                continue
            try:
                owner_loop.call_soon_threadsafe(
                    self._queue_event,
                    queue,
                    event,
                    resync_on_full,
                )
            except RuntimeError:
                # Subscriber loop may close between is_closed() and scheduling.
                continue

    async def emit(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        provisional: bool = False,
        event_id: str | None = None,
    ) -> RunEvent:
        async with self._async_lock():
            with self._thread_lock:
                event = RunEvent(
                    event_id=event_id or f"evt_{uuid4().hex[:12]}",
                    run_id=run_id,
                    type=event_type,
                    timestamp=time.time(),
                    sequence=self._next_seq(run_id),
                    payload=dict(payload or {}),
                    provisional=provisional,
                )
                bucket = self._events.setdefault(run_id, [])
                bucket.append(event)
                if len(bucket) > self.maxlen:
                    del bucket[: len(bucket) - self.maxlen]
                self._remember_terminal(event)
                subscribers = list(self._subscribers.get(run_id, []))
            self.reap()
            # Provisional stream deltas may be dropped under backpressure; durable/
            # terminal progress must instead tell the client to resync explicitly.
            self._fan_out(subscribers, event, resync_on_full=not provisional)
            self._persist(event)
            return event

    def emit_sync(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        provisional: bool = False,
    ) -> RunEvent:
        """Sync emit for worker threads; fan-out occurs on each subscriber's owning loop."""
        with self._thread_lock:
            event = RunEvent(
                event_id=f"evt_{uuid4().hex[:12]}",
                run_id=run_id,
                type=event_type,
                timestamp=time.time(),
                sequence=self._next_seq(run_id),
                payload=dict(payload or {}),
                provisional=provisional,
            )
            bucket = self._events.setdefault(run_id, [])
            bucket.append(event)
            if len(bucket) > self.maxlen:
                del bucket[: len(bucket) - self.maxlen]
            self._remember_terminal(event)
            subscribers = list(self._subscribers.get(run_id, []))
            self._persist(event)

        self.reap()
        # Fan-out outside the lock so slow consumers cannot stall producers.
        self._fan_out(subscribers, event, resync_on_full=not provisional)
        return event

    def history(self, run_id: str, *, after_sequence: int = 0) -> list[RunEvent]:
        self.reap()
        with self._thread_lock:
            return [event for event in self._events.get(run_id, []) if event.sequence > after_sequence]

    def latest(self, run_id: str) -> RunEvent | None:
        with self._thread_lock:
            events = self._events.get(run_id) or []
            return events[-1] if events else None

    async def subscribe(self, run_id: str, *, after_sequence: int | None = None) -> asyncio.Queue[RunEvent | None]:
        """Subscribe and optionally seed missed history under one lock to close the race."""
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(maxsize=256)
        owner_loop = asyncio.get_running_loop()
        async with self._async_lock():
            with self._thread_lock:
                self._subscribers.setdefault(run_id, []).append((queue, owner_loop))
                seed: list[RunEvent] = []
                if after_sequence is not None:
                    seed = [event for event in self._events.get(run_id, []) if event.sequence > after_sequence]
            for event in seed:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Explicit marker: reconnect history exceeded the subscriber
                    # buffer, so the client must recover from durable/history state.
                    self._queue_event(queue, event, resync_on_full=True)
                    break
        return queue

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue[RunEvent | None]) -> None:
        async with self._async_lock():
            with self._thread_lock:
                subscribers = self._subscribers.get(run_id) or []
                self._subscribers[run_id] = [subscriber for subscriber in subscribers if subscriber[0] is not queue]
                if not self._subscribers[run_id]:
                    self._subscribers.pop(run_id, None)

    def clear(self, run_id: str) -> None:
        with self._thread_lock:
            self._events.pop(run_id, None)
            self._seq.pop(run_id, None)


run_event_bus = RunEventBus()
