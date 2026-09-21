from __future__ import annotations

import threading
from typing import Any


class ResourceManager:
    """Bounded concurrency slots for job execution."""

    def __init__(self, max_job_concurrency: int = 1) -> None:
        if max_job_concurrency < 1:
            raise ValueError("max_job_concurrency must be >= 1")
        self.max_job_concurrency = max_job_concurrency
        self._semaphore = threading.Semaphore(max_job_concurrency)
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self.telemetry: dict[str, Any] = {
            "acquired": 0,
            "released": 0,
            "rejected": 0,
        }

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def active_job_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._active)

    def try_acquire(self, job_id: str) -> bool:
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            self.telemetry["rejected"] += 1
            return False
        with self._lock:
            self._active.add(job_id)
        self.telemetry["acquired"] += 1
        return True

    def rebind(self, old_id: str, new_id: str) -> None:
        """Rename an acquired slot holder without releasing the semaphore."""
        with self._lock:
            if old_id not in self._active:
                raise KeyError(f"No active slot for {old_id}")
            self._active.discard(old_id)
            self._active.add(new_id)

    def release(self, job_id: str) -> None:
        with self._lock:
            self._active.discard(job_id)
        self._semaphore.release()
        self.telemetry["released"] += 1
