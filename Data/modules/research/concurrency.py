"""Bounded concurrency helpers for research search/fetch (Wave 10–11).

Prevents unbounded fan-out when a plan lists many queries/URLs. Extends the
existing HostRateLimiter pattern — does not invent a second network stack.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_SEARCH_CONCURRENCY = 4
DEFAULT_FETCH_CONCURRENCY = 4
MAX_SEARCH_CONCURRENCY = 8
MAX_FETCH_CONCURRENCY = 8


@dataclass
class BoundedConcurrencyGate:
    """Semaphore-backed concurrency limit shared across search/fetch waves."""

    max_workers: int = DEFAULT_SEARCH_CONCURRENCY
    name: str = "research"
    _sem: threading.BoundedSemaphore = field(init=False, repr=False)
    acquisitions: int = 0
    rejections: int = 0

    def __post_init__(self) -> None:
        workers = max(1, min(int(self.max_workers), MAX_SEARCH_CONCURRENCY))
        self.max_workers = workers
        self._sem = threading.BoundedSemaphore(workers)

    def run_bounded(
        self,
        items: Sequence[T],
        fn: Callable[[T], R],
        *,
        max_workers: int | None = None,
    ) -> list[R | BaseException]:
        """Map ``fn`` over ``items`` with a hard concurrency ceiling.

        Exceptions are returned (not raised) so one bad URL/query cannot abort
        the whole wave. Caller decides fail-closed handling.
        """
        if not items:
            return []
        workers = max(1, min(int(max_workers or self.max_workers), MAX_FETCH_CONCURRENCY))
        results: list[R | BaseException] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._guarded, fn, item): idx for idx, item in enumerate(items)}
            ordered: list[R | BaseException | None] = [None] * len(items)
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    ordered[idx] = fut.result()
                except BaseException as exc:  # noqa: BLE001 — isolate per-item failure
                    ordered[idx] = exc
            results = [r if r is not None else RuntimeError("missing_result") for r in ordered]
        return results

    def _guarded(self, fn: Callable[[T], R], item: T) -> R:
        acquired = self._sem.acquire(blocking=True, timeout=120.0)
        if not acquired:
            self.rejections += 1
            raise TimeoutError(f"{self.name}_concurrency_acquire_timeout")
        self.acquisitions += 1
        try:
            return fn(item)
        finally:
            self._sem.release()

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_workers": self.max_workers,
            "acquisitions": self.acquisitions,
            "rejections": self.rejections,
            "truth": {
                "bounded_concurrency": True,
                "unbounded_fanout_forbidden": True,
            },
        }


def clamp_concurrency(value: int | None, *, default: int, ceiling: int) -> int:
    if value is None:
        return max(1, min(default, ceiling))
    return max(1, min(int(value), ceiling))


def partition_successes(results: Iterable[R | BaseException]) -> tuple[list[R], list[BaseException]]:
    ok: list[R] = []
    err: list[BaseException] = []
    for item in results:
        if isinstance(item, BaseException):
            err.append(item)
        else:
            ok.append(item)
    return ok, err
