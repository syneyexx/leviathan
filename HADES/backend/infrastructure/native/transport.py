"""JSON-RPC transport over a single native companion stdin/stdout pair."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Callable

from .errors import NativeRuntimeError

logger = logging.getLogger("hades.native.transport")

PROTOCOL_VERSION = 1
DEFAULT_REQUEST_TIMEOUT_S = 120.0
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class RpcTransport:
    """Request ID matching, framing, timeouts, and pending-call bookkeeping."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._pending: dict[str, dict[str, Any]] = {}
        self._write: Callable[[str], None] | None = None
        self._generation = 0
        self._alive = False

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def attach(self, write_fn: Callable[[str], None], *, generation: int) -> None:
        with self._lock:
            self._write = write_fn
            self._generation = int(generation)
            self._alive = True

    def detach(
        self,
        *,
        reason: str = "Native runtime connection closed.",
        shutting_down: bool = False,
        generation: int | None = None,
    ) -> bool:
        """Detach the active write path.

        When ``generation`` is provided, only detach if it still matches the
        current transport generation so teardown of an old connection cannot
        clear a newly attached process.
        """
        with self._lock:
            if generation is not None and int(generation) != self._generation:
                return False
            self._write = None
            self._alive = False
            code = "CANCELLED" if shutting_down else "INTERNAL_ERROR"
            for waiter in self._pending.values():
                waiter["error"] = NativeRuntimeError(code, reason)
                waiter["event"].set()
            self._pending.clear()
            self._cond.notify_all()
            return True

    def fail_pending(self, error: NativeRuntimeError) -> None:
        with self._lock:
            for waiter in self._pending.values():
                waiter["error"] = error
                waiter["event"].set()
            self._pending.clear()
            self._cond.notify_all()

    def fail_pending_for_generation(
        self,
        generation: int,
        error: NativeRuntimeError,
        *,
        shutting_down: bool = False,
    ) -> None:
        with self._lock:
            stale_ids = [rid for rid, waiter in self._pending.items() if waiter.get("generation") == generation]
            for rid in stale_ids:
                waiter = self._pending.pop(rid, None)
                if waiter is None:
                    continue
                if shutting_down:
                    waiter["error"] = NativeRuntimeError("CANCELLED", error.message)
                else:
                    waiter["error"] = error
                waiter["event"].set()
            self._cond.notify_all()

    def deliver(self, message: dict[str, Any], *, reader_generation: int | None = None) -> None:
        response_id = str(message.get("id") or "")
        expected_generation = self._generation if reader_generation is None else reader_generation
        with self._lock:
            waiter = self._pending.pop(response_id, None)
            if waiter is None:
                return
            # Stale generation protection — do not deliver cross-connection.
            if waiter.get("generation") != expected_generation:
                self._pending[response_id] = waiter
                return
            waiter["response"] = message
            waiter["event"].set()

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_s: float | None = None,
        on_timeout: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        payload = {
            "version": PROTOCOL_VERSION,
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise NativeRuntimeError("INVALID_REQUEST", "Request exceeds maximum message size.")
        timeout = DEFAULT_REQUEST_TIMEOUT_S if timeout_s is None else float(timeout_s)
        event = threading.Event()
        waiter: dict[str, Any] = {
            "event": event,
            "response": None,
            "error": None,
            "generation": None,
            "method": method,
        }
        with self._lock:
            if not self._alive or self._write is None:
                raise NativeRuntimeError("NATIVE_UNAVAILABLE", "Native runtime process is not running.")
            # Generation, registration, and send are one atomic step under the lock.
            waiter["generation"] = self._generation
            self._pending[request_id] = waiter
            try:
                self._write(raw + "\n")
            except Exception as exc:
                self._pending.pop(request_id, None)
                raise NativeRuntimeError("PROCESS_START_FAILED", f"Failed to write to native runtime: {exc}") from exc

        if not event.wait(timeout):
            with self._lock:
                current = self._pending.get(request_id)
                if current is waiter:
                    self._pending.pop(request_id, None)
                elif current is not None:
                    # Replaced / already completed under a different waiter — do not cancel.
                    pass
                else:
                    # Already delivered or failed; fall through to waiter fields.
                    pass
            # Only fire timeout cancel if this waiter still owns the timeout.
            if waiter["response"] is None and waiter["error"] is None:
                if on_timeout is not None:
                    try:
                        on_timeout(request_id, method)
                    except Exception as exc:
                        logger.debug("native timeout cancel hook failed: %s", exc)
                raise NativeRuntimeError(
                    "TIMEOUT",
                    f"Native request timed out after {timeout}s.",
                    {"method": method, "request_id": request_id},
                )

        if waiter["error"] is not None:
            err = waiter["error"]
            if isinstance(err, NativeRuntimeError):
                raise err
            raise NativeRuntimeError("INTERNAL_ERROR", str(err))
        response = waiter["response"] or {}
        if not response.get("ok", False):
            error = response.get("error") or {}
            raise NativeRuntimeError(
                str(error.get("code") or "INTERNAL_ERROR"),
                str(error.get("message") or "Native runtime error"),
                error.get("details") if isinstance(error.get("details"), dict) else {},
            )
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
