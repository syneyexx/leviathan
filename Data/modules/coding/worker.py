"""Background coding-session worker (daemon thread, DatasetJobRunner-style)."""

from __future__ import annotations

import threading
from typing import Callable

from .loop import CodingLoop
from .store import CodingStore
from .types import SessionStatus


class CodingWorker:
    """Polls for RUNNING sessions and advances CodingLoop rounds without blocking HTTP."""

    def __init__(self, store: CodingStore, loop: CodingLoop) -> None:
        self.store = store
        self.loop = loop
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()

    def start_background(self, *, poll_seconds: float = 0.25) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()

            def _loop() -> None:
                while not self._stop.is_set():
                    advanced = self.process_next()
                    if not advanced:
                        # Wait for wake or poll interval.
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
        """Advance one RUNNING session by one round. Returns True if work happened."""
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
            # Clear worker_pid when paused/terminal so another process can recover.
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
