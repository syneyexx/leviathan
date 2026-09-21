"""Lightweight in-process performance counters for HADES.

No secrets, no hidden reasoning, no extra observability stack.
Counters are process-local, bounded, and safe to snapshot from tests or diagnostics.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator


SLOW_SQLITE_MS = 50.0


@dataclass
class RequestTrace:
    started: float = field(default_factory=time.perf_counter)
    discover_calls: int = 0
    discover_hits: int = 0
    discover_misses: int = 0
    discover_ms: float = 0.0
    resolve_model_ms: float = 0.0
    retrieval_ms: float = 0.0
    memory_retrieval_ms: float = 0.0
    knowledge_retrieval_ms: float = 0.0
    retrieval_candidates: int = 0
    packed_hits: int = 0
    sqlite_opens: int = 0
    sqlite_ms: float = 0.0
    model_calls: int = 0
    model_queue_wait_ms: float = 0.0
    model_generation_ms: float = 0.0
    ttft_ms: float | None = None
    first_token_at: float | None = None

    def finish(self) -> dict[str, Any]:
        return {
            "total_ms": round((time.perf_counter() - self.started) * 1000, 2),
            "discover_calls": self.discover_calls,
            "discover_hits": self.discover_hits,
            "discover_misses": self.discover_misses,
            "discover_ms": round(self.discover_ms, 2),
            "resolve_model_ms": round(self.resolve_model_ms, 2),
            "retrieval_ms": round(self.retrieval_ms, 2),
            "memory_retrieval_ms": round(self.memory_retrieval_ms, 2),
            "knowledge_retrieval_ms": round(self.knowledge_retrieval_ms, 2),
            "retrieval_candidates": self.retrieval_candidates,
            "packed_hits": self.packed_hits,
            "sqlite_opens": self.sqlite_opens,
            "sqlite_ms": round(self.sqlite_ms, 2),
            "model_calls": self.model_calls,
            "model_queue_wait_ms": round(self.model_queue_wait_ms, 2),
            "model_generation_ms": round(self.model_generation_ms, 2),
            "ttft_ms": None if self.ttft_ms is None else round(self.ttft_ms, 2),
        }


class _Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.sqlite_opens = 0
            self.sqlite_commits = 0
            self.sqlite_ms = 0.0
            self.sqlite_slow = 0
            self.sqlite_busy = 0
            self.wal_passive = 0
            self.wal_truncate = 0
            self.wal_checkpoint_ms = 0.0
            self.discover_calls = 0
            self.discover_upstream = 0
            self.discover_hits = 0
            self.discover_misses = 0
            self.discover_ms = 0.0
            self.resolve_model_ms = 0.0
            self.model_calls = 0
            self.model_queue_wait_ms = 0.0
            self.model_generation_ms = 0.0
            self.ttft_samples = 0
            self.ttft_ms_total = 0.0
            self.retrieval_ms = 0.0
            self.memory_retrieval_ms = 0.0
            self.knowledge_retrieval_ms = 0.0
            self.last_request: dict[str, Any] | None = None

    def add(self, **delta: float | int) -> None:
        with self._lock:
            for key, value in delta.items():
                current = getattr(self, key)
                setattr(self, key, current + value)

    def set_last_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.last_request = payload

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ttft_avg = (
                round(self.ttft_ms_total / self.ttft_samples, 2) if self.ttft_samples else None
            )
            return {
                "sqlite": {
                    "opens": self.sqlite_opens,
                    "commits": self.sqlite_commits,
                    "time_ms": round(self.sqlite_ms, 2),
                    "slow_ops": self.sqlite_slow,
                    "busy": self.sqlite_busy,
                    "wal_passive": self.wal_passive,
                    "wal_truncate": self.wal_truncate,
                    "wal_checkpoint_ms": round(self.wal_checkpoint_ms, 2),
                },
                "discovery": {
                    "calls": self.discover_calls,
                    "upstream": self.discover_upstream,
                    "hits": self.discover_hits,
                    "misses": self.discover_misses,
                    "time_ms": round(self.discover_ms, 2),
                    "resolve_model_ms": round(self.resolve_model_ms, 2),
                },
                "model": {
                    "calls": self.model_calls,
                    "queue_wait_ms": round(self.model_queue_wait_ms, 2),
                    "generation_ms": round(self.model_generation_ms, 2),
                    "ttft_samples": self.ttft_samples,
                    "ttft_avg_ms": ttft_avg,
                },
                "retrieval": {
                    "time_ms": round(self.retrieval_ms, 2),
                    "memory_ms": round(self.memory_retrieval_ms, 2),
                    "knowledge_ms": round(self.knowledge_retrieval_ms, 2),
                },
                "last_request": dict(self.last_request) if self.last_request else None,
            }


counters = _Counters()
_current_trace: ContextVar[RequestTrace | None] = ContextVar("hades_perf_trace", default=None)


def current_trace() -> RequestTrace | None:
    return _current_trace.get()


@contextmanager
def request_trace() -> Iterator[RequestTrace]:
    trace = RequestTrace()
    token = _current_trace.set(trace)
    try:
        yield trace
    finally:
        payload = trace.finish()
        counters.set_last_request(payload)
        _current_trace.reset(token)


def record_sqlite(*, opens: int = 0, commits: int = 0, ms: float = 0.0, busy: int = 0) -> None:
    slow = 1 if ms >= SLOW_SQLITE_MS else 0
    counters.add(sqlite_opens=opens, sqlite_commits=commits, sqlite_ms=ms, sqlite_slow=slow, sqlite_busy=busy)
    trace = current_trace()
    if trace is not None:
        trace.sqlite_opens += opens
        trace.sqlite_ms += ms


def record_checkpoint(*, kind: str, ms: float) -> None:
    if kind == "truncate":
        counters.add(wal_truncate=1, wal_checkpoint_ms=ms)
    else:
        counters.add(wal_passive=1, wal_checkpoint_ms=ms)


def record_discover(*, hit: bool, ms: float, upstream: bool) -> None:
    counters.add(
        discover_calls=1,
        discover_hits=1 if hit else 0,
        discover_misses=0 if hit else 1,
        discover_ms=ms,
        discover_upstream=1 if upstream else 0,
    )
    trace = current_trace()
    if trace is None:
        return
    trace.discover_calls += 1
    if hit:
        trace.discover_hits += 1
    else:
        trace.discover_misses += 1
    trace.discover_ms += ms


def record_resolve_model(ms: float) -> None:
    counters.add(resolve_model_ms=ms)
    trace = current_trace()
    if trace is not None:
        trace.resolve_model_ms += ms


def record_retrieval(*, total_ms: float, memory_ms: float, knowledge_ms: float, candidates: int, packed: int) -> None:
    counters.add(
        retrieval_ms=total_ms,
        memory_retrieval_ms=memory_ms,
        knowledge_retrieval_ms=knowledge_ms,
    )
    trace = current_trace()
    if trace is None:
        return
    trace.retrieval_ms += total_ms
    trace.memory_retrieval_ms += memory_ms
    trace.knowledge_retrieval_ms += knowledge_ms
    trace.retrieval_candidates += candidates
    trace.packed_hits += packed


def record_model_call(*, queue_wait_ms: float = 0.0, generation_ms: float = 0.0) -> None:
    counters.add(model_calls=1, model_queue_wait_ms=queue_wait_ms, model_generation_ms=generation_ms)
    trace = current_trace()
    if trace is None:
        return
    trace.model_calls += 1
    trace.model_queue_wait_ms += queue_wait_ms
    trace.model_generation_ms += generation_ms


def record_first_token() -> None:
    trace = current_trace()
    if trace is None or trace.first_token_at is not None:
        return
    now = time.perf_counter()
    trace.first_token_at = now
    trace.ttft_ms = (now - trace.started) * 1000
    counters.add(ttft_samples=1, ttft_ms_total=trace.ttft_ms)


def snapshot() -> dict[str, Any]:
    return counters.snapshot()


def reset() -> None:
    counters.reset()
