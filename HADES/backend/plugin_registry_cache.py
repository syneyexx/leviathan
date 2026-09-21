"""Request-scoped plugin registry cache with global invalidation."""

from __future__ import annotations

import contextvars
import threading
from typing import Any, Callable

_registry_generation = 0
_registry_lock = threading.Lock()
_request_scope: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "plugin_registry_request_cache",
    default=None,
)


def invalidate_plugin_registry_cache() -> None:
    global _registry_generation
    with _registry_lock:
        _registry_generation += 1


def registry_generation() -> int:
    with _registry_lock:
        return _registry_generation


def begin_request_cache() -> None:
    _request_scope.set({"generation": registry_generation(), "plugins": None, "tools": None})


def end_request_cache() -> None:
    _request_scope.set(None)


def _bucket() -> dict[str, Any] | None:
    bucket = _request_scope.get()
    if bucket is None:
        return None
    if bucket.get("generation") != registry_generation():
        bucket["generation"] = registry_generation()
        bucket["plugins"] = None
        bucket["tools"] = None
    return bucket


def cached_list_plugins(list_fn: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    bucket = _bucket()
    if bucket is None:
        return list_fn()
    if bucket["plugins"] is None:
        bucket["plugins"] = list_fn()
    return list(bucket["plugins"])


def cached_plugin_tools(tools_fn: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    bucket = _bucket()
    if bucket is None:
        return tools_fn()
    if bucket["tools"] is None:
        bucket["tools"] = tools_fn()
    return list(bucket["tools"])
