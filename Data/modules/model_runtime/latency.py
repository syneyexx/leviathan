"""Separated serving latency stages — Round 6 honesty (never conflate into one number).

Stages:
  queue   — time waiting for admission / capacity
  prefill — prompt processing before first token (when measured)
  ttft    — time to first token from admit/start
  decode  — generation after first token
  tool    — tool / capability round-trips inside the task
  total   — end-to-end wall clock

None means UNMEASURED, not zero.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LatencyBreakdown:
    queue_ms: float | None = None
    prefill_ms: float | None = None
    ttft_ms: float | None = None
    decode_ms: float | None = None
    tool_ms: float | None = None
    total_ms: float | None = None
    source: str = "unmeasured"

    def public_dict(self) -> dict[str, Any]:
        return {
            "queue_ms": self.queue_ms,
            "prefill_ms": self.prefill_ms,
            "ttft_ms": self.ttft_ms,
            "decode_ms": self.decode_ms,
            "tool_ms": self.tool_ms,
            "total_ms": self.total_ms,
            "source": self.source,
            "truth": {
                "stages_are_separated": True,
                "unmeasured_is_not_zero": True,
                "single_latency_is_not_enough": True,
            },
        }


@dataclass
class LatencyTimer:
    """Accumulate stage timings from monotonic clocks."""

    _t0: float = field(default_factory=time.perf_counter)
    _queue_start: float | None = None
    _queue_ms: float | None = None
    _admit_at: float | None = None
    _first_token_at: float | None = None
    _prefill_ms: float | None = None
    _tool_ms: float = 0.0
    _tool_open: float | None = None

    def begin_queue(self) -> None:
        self._queue_start = time.perf_counter()

    def end_queue(self) -> None:
        if self._queue_start is None:
            return
        self._queue_ms = (time.perf_counter() - self._queue_start) * 1000.0
        self._admit_at = time.perf_counter()
        self._queue_start = None

    @property
    def queue_ms(self) -> float | None:
        return self._queue_ms

    def mark_admitted(self) -> None:
        if self._admit_at is None:
            self._admit_at = time.perf_counter()
            if self._queue_ms is None:
                self._queue_ms = (self._admit_at - self._t0) * 1000.0

    def mark_first_token(self, *, prefill_ms: float | None = None) -> None:
        if self._first_token_at is not None:
            return
        now = time.perf_counter()
        self._first_token_at = now
        if self._admit_at is not None:
            self._prefill_ms = prefill_ms if prefill_ms is not None else (now - self._admit_at) * 1000.0
        elif prefill_ms is not None:
            self._prefill_ms = prefill_ms

    def begin_tool(self) -> None:
        self._tool_open = time.perf_counter()

    def end_tool(self) -> None:
        if self._tool_open is None:
            return
        self._tool_ms += (time.perf_counter() - self._tool_open) * 1000.0
        self._tool_open = None

    def finish(self, *, source: str = "measured") -> LatencyBreakdown:
        now = time.perf_counter()
        total = (now - self._t0) * 1000.0
        ttft: float | None = None
        decode: float | None = None
        if self._first_token_at is not None and self._admit_at is not None:
            ttft = (self._first_token_at - self._admit_at) * 1000.0
            decode = (now - self._first_token_at) * 1000.0
        elif self._first_token_at is not None:
            ttft = (self._first_token_at - self._t0) * 1000.0
            decode = (now - self._first_token_at) * 1000.0
        return LatencyBreakdown(
            queue_ms=self._queue_ms,
            prefill_ms=self._prefill_ms,
            ttft_ms=ttft,
            decode_ms=decode,
            tool_ms=self._tool_ms if self._tool_ms > 0 else (0.0 if source == "measured" else None),
            total_ms=total,
            source=source,
        )
