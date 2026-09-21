"""Bounded TTL + request-scoped cache for LM Studio /models discovery."""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from perf import record_discover

FetchModels = Callable[[], Awaitable[tuple[list[dict[str, Any]], float]]]

_request_models: ContextVar[tuple[str, list[dict[str, Any]], float] | None] = ContextVar(
    "hades_request_models",
    default=None,
)


class ModelDiscoveryCache:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._value: tuple[str, list[dict[str, Any]], float] | None = None
        self._expires_at = 0.0

    def clear(self, key: str | None = None) -> None:
        if key is None or (self._value and self._value[0] == key):
            self._value = None
            self._expires_at = 0.0

    async def get(
        self,
        key: str,
        fetch: FetchModels,
        *,
        ttl_s: float,
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], float, bool, bool]:
        """Return (models, latency_ms, cache_hit, did_upstream)."""
        scoped = _request_models.get()
        if not force and scoped and scoped[0] == key:
            record_discover(hit=True, ms=0.0, upstream=False)
            return scoped[1], scoped[2], True, False

        async with self._lock:
            now = time.monotonic()
            if (
                not force
                and self._value
                and self._value[0] == key
                and now < self._expires_at
            ):
                models, latency = self._value[1], self._value[2]
                record_discover(hit=True, ms=0.0, upstream=False)
                _request_models.set((key, models, latency))
                return models, latency, True, False

            started = time.perf_counter()
            models, latency = await fetch()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if latency is None:
                latency = round(elapsed_ms, 1)
            # Empty lists are cacheable only for a very short time so a later
            # load is observed quickly; failures must not be stored as success.
            if models:
                ttl = max(1.0, float(ttl_s))
                self._value = (key, list(models), float(latency))
                self._expires_at = time.monotonic() + ttl
                _request_models.set((key, list(models), float(latency)))
            else:
                self._value = None
                self._expires_at = 0.0
                _request_models.set(None)
            record_discover(hit=False, ms=elapsed_ms, upstream=True)
            return list(models), float(latency), False, True


cache = ModelDiscoveryCache()


def begin_request_discovery() -> None:
    _request_models.set(None)


def end_request_discovery() -> None:
    _request_models.set(None)


def invalidate(key: str | None = None) -> None:
    cache.clear(key)
    _request_models.set(None)
