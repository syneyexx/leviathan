"""Mission-scoped MCPMarket discovery cache. No model calls."""

from __future__ import annotations

import time
from typing import Any

from .official import DEFAULT_TTL_SECONDS


class DiscoveryCache:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def key(self, *, mission_id: str, requirement: str) -> str:
        return f"{mission_id}|{requirement.strip().lower()}"

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._items.get(key)
        if not row:
            return None
        ts, payload = row
        if time.time() - ts > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        copied = dict(payload)
        copied["cache"] = "hit"
        return copied

    def put(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        stored = dict(payload)
        stored["cache"] = "stored"
        self._items[key] = (time.time(), stored)
        return dict(stored)

    def invalidate(self, prefix: str | None = None) -> int:
        if prefix is None:
            n = len(self._items)
            self._items.clear()
            return n
        keys = [key for key in self._items if key.startswith(prefix)]
        for key in keys:
            self._items.pop(key, None)
        return len(keys)
