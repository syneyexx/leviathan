"""Bounded worker queue for long-running lab work.

Backtests, searches and evaluations take minutes, not milliseconds, so they must not run
inside a request handler. They run here: a small, fixed pool of worker threads draining a
SQLite-backed queue.

Bounded on purpose. The pool size is a hard ceiling and the queue rejects new work when it is
full, because an unbounded queue on a local workstation turns into an out-of-memory crash with
no useful error. Rejection with a clear reason is the better failure.

Every job supports pause, resume and cancel. Pause and cancel are cooperative: the handler
receives a :class:`SimulationControl` and checks it between events, so a stopped job stops at
a consistent point rather than mid-write.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from trading_lab.clock import SimulationControl
from trading_lab.contracts import stable_hash, utc_iso

JobHandler = Callable[["JobHandle"], dict[str, Any]]

TERMINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass
class JobHandle:
    """What a handler receives: its payload, its controls and its progress channel."""

    job_id: str
    kind: str
    payload: dict[str, Any]
    control: SimulationControl
    checkpoint: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    _progress: Callable[[dict[str, Any]], None] | None = None
    _checkpoint_writer: Callable[[dict[str, Any]], None] | None = None

    def progress(self, payload: dict[str, Any]) -> None:
        if self._progress:
            self._progress(payload)

    def save_checkpoint(self, payload: dict[str, Any]) -> None:
        if self._checkpoint_writer:
            self._checkpoint_writer(payload)

    @property
    def cancelled(self) -> bool:
        return self.control.cancelled

    @property
    def paused(self) -> bool:
        return self.control.paused


class JobQueueFull(RuntimeError):
    pass


class JobQueue:
    def __init__(
        self,
        store: Any,
        *,
        max_workers: int = 2,
        max_queued: int = 64,
    ) -> None:
        self.store = store
        self.max_workers = max(1, int(max_workers))
        self.max_queued = max(1, int(max_queued))
        self._handlers: dict[str, JobHandler] = {}
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=self.max_queued)
        self._controls: dict[str, SimulationControl] = {}
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._running = False
        self._progress_cache: dict[str, dict[str, Any]] = {}

    # --- lifecycle ---------------------------------------------------------------

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return {"started": False, "reason": "already_running", "workers": len(self._threads)}
            self._running = True
            requeued = self.store.requeue_interrupted_jobs()
            for index in range(self.max_workers):
                thread = threading.Thread(target=self._worker, name=f"trading-lab-worker-{index}", daemon=True)
                thread.start()
                self._threads.append(thread)
        for job in self.store.list_jobs(status="retry", limit=self.max_queued):
            self._offer(job["job_id"])
        for job in self.store.list_jobs(status="queued", limit=self.max_queued):
            self._offer(job["job_id"])
        return {"started": True, "workers": self.max_workers, "requeued": requeued}

    def stop(self, *, timeout: float = 5.0) -> dict[str, Any]:
        with self._lock:
            self._running = False
            for control in self._controls.values():
                control.cancel()
        for _ in self._threads:
            try:
                self._queue.put_nowait("__stop__")
            except queue.Full:
                break
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()
        return {"stopped": True}

    # --- submission --------------------------------------------------------------

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        job_key: str | None = None,
        priority: int = 5,
        max_attempts: int = 2,
        ref_type: str = "",
        ref_id: str = "",
    ) -> dict[str, Any]:
        if kind not in self._handlers:
            raise ValueError(f"unknown_job_kind:{kind}")
        key = job_key or f"{kind}:{stable_hash(payload)}"
        job = self.store.enqueue_job(
            job_key=key,
            kind=kind,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts,
            ref_type=ref_type,
            ref_id=ref_id,
        )
        if job.get("status") in TERMINAL_STATES:
            return job
        self._offer(job["job_id"])
        return job

    def _offer(self, job_id: str) -> None:
        try:
            self._queue.put_nowait(job_id)
        except queue.Full as exc:
            self.store.update_job(
                job_id,
                status="failed",
                error=(
                    f"queue_full: the lab accepts at most {self.max_queued} pending jobs. "
                    "Wait for running work to finish or cancel something."
                ),
                finished_at=utc_iso(datetime.now(tz=UTC)),
            )
            raise JobQueueFull(f"queue_full:{self.max_queued}") from exc

    # --- control -----------------------------------------------------------------

    def control_for(self, job_id: str) -> SimulationControl | None:
        return self._controls.get(job_id)

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        control = self._controls.get(job_id)
        if control is not None:
            control.cancel()
            return self.store.get_job(job_id)
        job = self.store.get_job(job_id)
        if job and job.get("status") in {"queued", "retry", "paused"}:
            return self.store.update_job(
                job_id, status="cancelled", finished_at=utc_iso(datetime.now(tz=UTC)), error="cancelled_before_start"
            )
        return job

    def pause(self, job_id: str) -> dict[str, Any] | None:
        control = self._controls.get(job_id)
        if control is not None:
            control.pause()
        return self.store.update_job(job_id, status="paused")

    def resume(self, job_id: str, *, speed: float | None = None) -> dict[str, Any] | None:
        control = self._controls.get(job_id)
        if control is not None:
            control.play(speed)
            return self.store.update_job(job_id, status="running")
        job = self.store.get_job(job_id)
        if job and job.get("status") in {"paused", "retry", "queued"}:
            self._offer(job_id)
            return self.store.update_job(job_id, status="queued")
        return job

    def step(self, job_id: str, count: int = 1) -> dict[str, Any] | None:
        control = self._controls.get(job_id)
        if control is not None:
            control.step(count)
        return self.store.get_job(job_id)

    def set_speed(self, job_id: str, speed: float) -> dict[str, Any] | None:
        control = self._controls.get(job_id)
        if control is not None:
            control.play(speed)
        return self.store.get_job(job_id)

    def progress(self, job_id: str) -> dict[str, Any]:
        return self._progress_cache.get(job_id, {})

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "workers": len(self._threads),
            "max_workers": self.max_workers,
            "queued": self._queue.qsize(),
            "max_queued": self.max_queued,
            "active_jobs": sorted(self._controls),
            "kinds": sorted(self._handlers),
        }

    # --- worker ------------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            try:
                job_id = self._queue.get(timeout=1.0)
            except queue.Empty:
                if not self._running:
                    return
                continue
            if job_id == "__stop__":
                self._queue.task_done()
                return
            try:
                self._execute(job_id)
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        job = self.store.claim_job(job_id)
        if job is None:
            return
        handler = self._handlers.get(job["kind"])
        if handler is None:
            self.store.update_job(
                job_id, status="failed", error=f"no_handler_for_kind:{job['kind']}", finished_at=utc_iso(datetime.now(tz=UTC))
            )
            return
        control = SimulationControl()
        control.play(100_000)
        self._controls[job_id] = control
        handle = JobHandle(
            job_id=job_id,
            kind=job["kind"],
            payload=job.get("payload") or {},
            control=control,
            checkpoint=job.get("checkpoint") or {},
            attempt=int(job.get("attempts", 1)),
            _progress=lambda payload: self._record_progress(job_id, payload),
            _checkpoint_writer=lambda payload: self.store.update_job(job_id, checkpoint=payload),
        )
        try:
            result = handler(handle)
            status = "cancelled" if control.cancelled else "completed"
            self.store.update_job(
                job_id,
                status=status,
                result=result,
                progress=100 if status == "completed" else self._progress_cache.get(job_id, {}).get("percent", 0),
                finished_at=utc_iso(datetime.now(tz=UTC)),
            )
        except Exception as exc:  # noqa: BLE001 - recorded, then retried or failed
            detail = f"{type(exc).__name__}: {exc}"
            trace = traceback.format_exc(limit=6)
            attempts = int(job.get("attempts", 1))
            max_attempts = int(job.get("max_attempts", 1))
            if attempts < max_attempts and not control.cancelled:
                self.store.update_job(job_id, status="retry", error=detail)
                self._offer(job_id)
            else:
                self.store.update_job(
                    job_id,
                    status="failed",
                    error=f"{detail}\n{trace}"[:4000],
                    finished_at=utc_iso(datetime.now(tz=UTC)),
                )
        finally:
            self._controls.pop(job_id, None)

    def _record_progress(self, job_id: str, payload: dict[str, Any]) -> None:
        self._progress_cache[job_id] = payload
        percent = payload.get("percent")
        if isinstance(percent, (int, float)):
            self.store.update_job(job_id, progress=int(max(0, min(100, percent))))


__all__ = ["JobHandle", "JobQueue", "JobQueueFull", "TERMINAL_STATES"]
