"""Per-host rate limiting with Retry-After / 429 / 503 backoff."""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict


class HostRateLimiter:
    def __init__(self, rate_limit_ms: int = 750) -> None:
        self.rate_limit_ms = max(0, int(rate_limit_ms))
        self._next_ok: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, host: str) -> None:
        host = (host or "").lower()
        lock = self._locks[host]
        async with lock:
            now = time.monotonic()
            delay = self._next_ok[host] - now
            if delay > 0:
                await asyncio.sleep(delay)
            jitter = random.uniform(0, min(0.25, self.rate_limit_ms / 1000.0 * 0.2)) if self.rate_limit_ms else 0
            self._next_ok[host] = time.monotonic() + (self.rate_limit_ms / 1000.0) + jitter

    def penalize(self, host: str, *, retry_after: float | None = None, status: int | None = None) -> None:
        host = (host or "").lower()
        base = retry_after if retry_after is not None else 0.0
        if status in {429, 503} and base <= 0:
            base = 5.0
        if base <= 0:
            base = (self.rate_limit_ms / 1000.0) * 2
        # Exponential-ish floor with jitter
        self._next_ok[host] = max(self._next_ok[host], time.monotonic() + base + random.uniform(0.1, 1.0))
