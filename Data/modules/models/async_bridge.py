"""Shared sync↔async bridge for Cognition / Coding callers.

Avoids creating a new event loop per inference when already inside one.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, TypeVar

T = TypeVar("T")

_bridge_pool: concurrent.futures.ThreadPoolExecutor | None = None


def _pool() -> concurrent.futures.ThreadPoolExecutor:
    global _bridge_pool
    if _bridge_pool is None:
        _bridge_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="leviathan-async-bridge"
        )
    return _bridge_pool


def run_coro_sync(coro: Any, *, timeout: float | None = 600.0) -> Any:
    """Run an async coroutine from sync code without nesting event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    future = _pool().submit(asyncio.run, coro)
    return future.result(timeout=timeout)
