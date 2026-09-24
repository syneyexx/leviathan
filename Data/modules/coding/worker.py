"""Background coding-session worker — JobRuntime-compatible lease executor.

Canonical schedulable work is enqueued as ``coding.advance`` jobs when a
JobRuntime is bound. This worker remains the domain executor (like the
source-ingestion external worker pattern) so HTTP stays non-blocking and
future external worker processes can claim the same jobs.
"""

from __future__ import annotations

import threading
from typing import Any

from Data.modules.jobs.states import JobState

from .loop import CodingLoop
from .store import CodingStore
from .types import SessionStatus


class CodingWorker:
    """Advance coding sessions via JobRuntime leases or legacy session claims."""

    def __init__(
        self,
        store: CodingStore,
        loop: CodingLoop,
        *,
        job_runtime: Any | None = None,
    ) -> None:
        self.store = store
        self.loop = loop
        self.job_runtime = job_runtime
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def start_background(self, *, poll_seconds: float = 0.25) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()

            def _loop() -> None:
                while not self._stop.is_set():
                    advanced = self.process_next()
                    if not advanced:
                        self._wake.wait(poll_seconds)
                        self._wake.clear()

            self._thread = threading.Thread(target=_loop, name="coding-worker", daemon=True)
            self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def process_next(self) -> bool:
        """Advance one coding.advance job or one RUNNING session. Returns True if work happened."""
        if self.job_runtime is not None and self._process_job_lease():
            return True
        return self._process_session_claim()

    def _process_job_lease(self) -> bool:
        runtime = self.job_runtime
        if runtime is None:
            return False
        store = getattr(runtime, "store", None)
        if store is None:
            return False
        # Prefer explicit coding.advance jobs via JobStore claim.
        job = None
        try:
            if hasattr(store, "claim_next_queued"):
                job = store.claim_next_queued(capability_ids={"coding.advance"})
        except Exception:  # noqa: BLE001
            job = None
        if job is None:
            return False
        leased = job
        args = dict(getattr(leased, "arguments", None) or {})
        session_id = str(args.get("session_id") or "")
        approval_id = args.get("approval_id")
        if not session_id:
            try:
                store.transition(leased.job_id, JobState.FAILED, error="missing session_id")
            except Exception:  # noqa: BLE001
                pass
            return True
        session = self.store.get_session(session_id)
        if session is None:
            try:
                store.transition(leased.job_id, JobState.FAILED, error="session not found")
            except Exception:  # noqa: BLE001
                pass
            return True
        if session.cancel_requested:
            self.store.update_session(
                session_id,
                status=SessionStatus.CANCELLED,
                error="cancelled",
                worker_pid=None,
            )
            try:
                store.transition(leased.job_id, JobState.CANCELLED)
            except Exception:  # noqa: BLE001
                pass
            return True
        try:
            approval_ids = [str(approval_id)] if approval_id else None
            result = self.loop.run_round(session_id, approval_ids=approval_ids)
            if result.status == SessionStatus.RUNNING:
                try:
                    store.transition(leased.job_id, JobState.COMPLETED)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    runtime.enqueue(
                        capability_id="coding.advance",
                        arguments={"session_id": session_id},
                        run_id=session.run_id,
                        requested_by="coding.worker",
                        idempotency_key=f"coding.advance:{session_id}:{result.session.round_count}",
                        metadata={"session_id": session_id, "continuation": True},
                    )
                except Exception:  # noqa: BLE001
                    self.store.update_session(session_id, status=SessionStatus.RUNNING, worker_pid=None)
                return True
            self.store.update_session(session_id, worker_pid=None)
            try:
                store.transition(leased.job_id, JobState.COMPLETED)
            except Exception:  # noqa: BLE001
                pass
            return True
        except Exception as exc:  # noqa: BLE001
            self.store.update_session(
                session_id,
                status=SessionStatus.FAILED,
                error=str(exc)[:2000],
                worker_pid=None,
            )
            try:
                store.transition(leased.job_id, JobState.FAILED, error=str(exc)[:2000])
            except Exception:  # noqa: BLE001
                pass
            return True

    def _process_session_claim(self) -> bool:
        """Compatibility path when jobs are not used or need recovery."""
        session = self.store.claim_next_runnable()
        if session is None:
            return False
        if session.cancel_requested:
            self.store.update_session(
                session.session_id,
                status=SessionStatus.CANCELLED,
                error="cancelled",
                worker_pid=None,
            )
            return True
        try:
            result = self.loop.run_round(session.session_id)
            if result.status != SessionStatus.RUNNING:
                self.store.update_session(session.session_id, worker_pid=None)
            return True
        except Exception as exc:  # noqa: BLE001
            self.store.update_session(
                session.session_id,
                status=SessionStatus.FAILED,
                error=str(exc)[:2000],
                worker_pid=None,
            )
            return True

    def drain(self, *, max_rounds: int = 50) -> int:
        """Synchronously process up to max_rounds (tests / foreground)."""
        count = 0
        for _ in range(max_rounds):
            if not self.process_next():
                break
            count += 1
        return count
