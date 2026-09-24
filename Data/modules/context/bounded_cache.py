"""Bounded size-aware LRU caches for deterministic derived acceleration.

Never stores canonical Brain/history/domain state. Eviction never deletes
authoritative data — only derived cache entries.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheStats:
    lookups: int = 0
    hits: int = 0
    misses: int = 0
    bypasses: int = 0
    inserts: int = 0
    evictions: int = 0
    invalidations: int = 0
    bytes_estimate: int = 0

    def public_dict(self) -> dict[str, Any]:
        hit_rate = (self.hits / self.lookups) if self.lookups else None
        return {
            "lookups": self.lookups,
            "hits": self.hits,
            "misses": self.misses,
            "bypasses": self.bypasses,
            "inserts": self.inserts,
            "evictions": self.evictions,
            "invalidations": self.invalidations,
            "bytesEstimate": self.bytes_estimate,
            "hitRate": hit_rate,
            "truth": {
                "hit_rate_is_measured": hit_rate is not None,
                "bytes_are_estimated": True,
            },
        }


def _default_sizeof(value: Any) -> int:
    try:
        if isinstance(value, (bytes, bytearray)):
            return len(value)
        if isinstance(value, str):
            return len(value.encode("utf-8", errors="replace"))
        if isinstance(value, dict):
            return sum(_default_sizeof(k) + _default_sizeof(v) for k, v in value.items())
        if isinstance(value, (list, tuple, set)):
            return sum(_default_sizeof(v) for v in value)
        # Rough fallback for dataclasses / simple objects
        return 64 + len(repr(value))
    except Exception:  # noqa: BLE001
        return 64


@dataclass
class _Entry(Generic[V]):
    value: V
    size: int
    created_at: float = field(default_factory=time.monotonic)
    generation: int = 0


class BoundedLRUCache(Generic[K, V]):
    """Thread-safe size+entry bounded LRU with optional TTL and generation."""

    def __init__(
        self,
        *,
        max_entries: int = 1024,
        max_bytes: int = 8 * 1024 * 1024,
        ttl_seconds: float | None = None,
        sizeof: Callable[[V], int] | None = None,
        name: str = "cache",
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if max_bytes < 64:
            raise ValueError("max_bytes must be >= 64")
        self.name = name
        self.max_entries = int(max_entries)
        self.max_bytes = int(max_bytes)
        self.ttl_seconds = float(ttl_seconds) if ttl_seconds is not None else None
        self._sizeof = sizeof or _default_sizeof
        self._lock = threading.RLock()
        self._data: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._bytes = 0
        self.stats = CacheStats()
        self._generation = 0
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def bump_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def clear(self) -> int:
        with self._lock:
            n = len(self._data)
            self._data.clear()
            self._bytes = 0
            self.stats.invalidations += n
            self.stats.bytes_estimate = 0
            return n

    def invalidate_matching(self, predicate: Callable[[K, V], bool]) -> int:
        with self._lock:
            doomed = [k for k, e in self._data.items() if predicate(k, e.value)]
            for k in doomed:
                entry = self._data.pop(k)
                self._bytes -= entry.size
                self.stats.invalidations += 1
            self.stats.bytes_estimate = self._bytes
            return len(doomed)

    def get(self, key: K) -> V | None:
        with self._lock:
            self.stats.lookups += 1
            if not self._enabled:
                self.stats.bypasses += 1
                return None
            entry = self._data.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            if self.ttl_seconds is not None and (time.monotonic() - entry.created_at) > self.ttl_seconds:
                self._data.pop(key, None)
                self._bytes -= entry.size
                self.stats.misses += 1
                self.stats.evictions += 1
                self.stats.bytes_estimate = self._bytes
                return None
            self._data.move_to_end(key)
            self.stats.hits += 1
            return entry.value

    def put(self, key: K, value: V, *, generation: int | None = None) -> None:
        with self._lock:
            if not self._enabled:
                self.stats.bypasses += 1
                return
            size = max(1, int(self._sizeof(value)))
            if key in self._data:
                old = self._data.pop(key)
                self._bytes -= old.size
            entry = _Entry(value=value, size=size, generation=generation if generation is not None else self._generation)
            self._data[key] = entry
            self._bytes += size
            self.stats.inserts += 1
            self._evict_overflow()
            self.stats.bytes_estimate = self._bytes

    def _evict_overflow(self) -> None:
        while self._data and (len(self._data) > self.max_entries or self._bytes > self.max_bytes):
            _k, entry = self._data.popitem(last=False)
            self._bytes -= entry.size
            self.stats.evictions += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "enabled": self._enabled,
                "entries": len(self._data),
                "maxEntries": self.max_entries,
                "maxBytes": self.max_bytes,
                "bytesEstimate": self._bytes,
                "generation": self._generation,
                "ttlSeconds": self.ttl_seconds,
                "stats": self.stats.public_dict(),
            }
