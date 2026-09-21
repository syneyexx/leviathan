"""TTL-cached expensive health probes (LM Studio, MCP).

Success responses may be served briefly from cache to protect frequent UI polling.
Error/disconnected states are never cached as healthy — failures use a zero TTL so
the next request re-probes immediately (no stale false-green).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

DEFAULT_SUCCESS_TTL_SECONDS = 8.0
ERROR_TTL_SECONDS = 0.0


@dataclass(slots=True)
class _ProbeEntry:
    value: Any
    expires_at: float
    is_healthy: bool


class ProbeTTLCache:
    def __init__(self, *, success_ttl: float = DEFAULT_SUCCESS_TTL_SECONDS) -> None:
        self._success_ttl = float(success_ttl)
        self._entries: dict[str, _ProbeEntry] = {}

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)

    def get_if_fresh(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            self._entries.pop(key, None)
            return None
        return entry.value

    def store(self, key: str, value: Any, *, healthy: bool) -> None:
        ttl = self._success_ttl if healthy else ERROR_TTL_SECONDS
        if ttl <= 0 and not healthy:
            # Do not retain error payloads — force immediate re-probe next tick.
            self._entries.pop(key, None)
            return
        self._entries[key] = _ProbeEntry(
            value=value,
            expires_at=time.monotonic() + ttl,
            is_healthy=healthy,
        )

    async def get_or_probe(
        self,
        key: str,
        probe: Callable[[], Awaitable[T]],
        *,
        healthy: Callable[[T], bool],
    ) -> tuple[T, bool]:
        """Return (value, cache_hit)."""
        cached = self.get_if_fresh(key)
        if cached is not None:
            return cached, True
        value = await probe()
        self.store(key, value, healthy=healthy(value))
        return value, False


health_probe_cache = ProbeTTLCache()
