"""Coding model-call control plane: ownership, timeout, cancel, cleanup.

Layer ownership
---------------
Layer 1 — Coding operation deadline (this module):
  Creates/registers the asyncio Task, awaits with a bounded timeout, and on
  timeout/cancel cancels that Task on its *owning* event loop, then waits for
  unwind before returning. Typed outcomes: ok / timeout / cancelled / error.

Layer 2 — Provider HTTP timeout (httpx / OmniRoute AsyncClient):
  Connection + read bounds on the wire. Does not replace Layer 1.

Identity
--------
* ``run_id`` — durable Coding cancellation identity. For async Coding jobs this
  is the ``job_id`` (exists before any Build/worktree run id). For sync
  ``/build/goal`` an ephemeral ``coding-sync-*`` id is allocated.
* ``call_id`` — one individual model request within a run.

Pause vs Cancel
---------------
Pause remains cooperative between atomic actions. Cancel fences the run and
cancels every active model Task so the underlying HTTP request cannot keep
generating tokens after HADES reported cancel/timeout.

Threading
---------
Coding workers are sync threads. Model coroutines run on a single dedicated
broker event loop (``hades-coding-lm-broker``). Cross-thread cancel uses
``loop.call_soon_threadsafe(task.cancel)`` — never foreign-loop ``aclose()``
as the primary cancel path, and never ``Future.cancel()`` alone.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

OutcomeKind = Literal["ok", "timeout", "cancelled", "error"]

_CANCELLED_RUN_CAP = 512
_CLEANUP_GRACE_S = 30.0
_BROKER_NAME = "hades-coding-lm-broker"


class CodingModelCancelled(Exception):
    """Typed cancellation of a Coding model call (user cancel or fence)."""

    def __init__(self, message: str = "coding_model_cancelled", *, run_id: str | None = None, phase: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.phase = phase
        self.kind = "cancelled"


class CodingModelTimeout(Exception):
    """Typed timeout of a Coding model call (underlying Task was cancelled)."""

    def __init__(self, message: str = "coding_model_timeout", *, run_id: str | None = None, phase: str | None = None, timeout_s: float | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.phase = phase
        self.timeout_s = timeout_s
        self.kind = "timeout"


@dataclass(slots=True)
class CodingModelResult:
    kind: OutcomeKind
    response: Any | None = None
    error: str | None = None
    call_id: str | None = None
    run_id: str | None = None
    phase: str = "model"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.kind == "ok"

    def to_invoke_meta(self) -> dict[str, Any]:
        """Compatibility shape for legacy propose/repair parsers."""
        meta = {
            "worker_ownership": "coding_model_runtime",
            "call_id": self.call_id,
            "run_id": self.run_id,
            "phase": self.phase,
            "outcome": self.kind,
            **dict(self.meta),
        }
        if self.kind == "timeout":
            timeout_s = self.meta.get("timeout_s")
            meta["note"] = f"lm_invoke_timeout:{timeout_s}"
            meta["cancel_signaled"] = True
            meta["underlying_cancelled"] = True
        elif self.kind == "cancelled":
            meta["note"] = "lm_invoke_cancelled"
            meta["cancel_signaled"] = True
            meta["underlying_cancelled"] = True
        elif self.kind == "error":
            meta["note"] = f"lm_invoke_failed:{self.error or 'error'}"
        return meta


@dataclass
class _ActiveCall:
    call_id: str
    run_id: str
    phase: str
    started_at: float
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task[Any] | None = None
    done: threading.Event = field(default_factory=threading.Event)


_registry_lock = threading.RLock()
_active_by_run: dict[str, dict[str, _ActiveCall]] = {}
_active_by_call: dict[str, _ActiveCall] = {}
_cancelled_runs: OrderedDict[str, float] = OrderedDict()

_broker_lock = threading.Lock()
_broker_loop: asyncio.AbstractEventLoop | None = None
_broker_thread: threading.Thread | None = None
_broker_ready = threading.Event()


def new_coding_run_id(*, prefix: str = "coding-sync") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def is_coding_run_cancelled(run_id: str | None) -> bool:
    if not run_id:
        return False
    with _registry_lock:
        if run_id in _cancelled_runs:
            return True
    try:
        from lm_studio import run_is_cancelled

        return bool(run_is_cancelled(run_id))
    except Exception:
        return False


def fence_coding_run(run_id: str | None) -> None:
    """Record cancel-before-register fence so later model calls fail closed."""
    if not run_id:
        return
    with _registry_lock:
        _cancelled_runs.pop(run_id, None)
        _cancelled_runs[run_id] = time.time()
        while len(_cancelled_runs) > _CANCELLED_RUN_CAP:
            _cancelled_runs.popitem(last=False)
    try:
        from lm_studio import remember_cancelled_run

        remember_cancelled_run(run_id)
    except Exception:
        pass


def clear_coding_run_fence(run_id: str | None) -> None:
    """Test/helper: remove a cancel fence without affecting other runs."""
    if not run_id:
        return
    with _registry_lock:
        _cancelled_runs.pop(run_id, None)


def active_coding_calls(run_id: str | None = None) -> list[dict[str, Any]]:
    with _registry_lock:
        if run_id:
            calls = list((_active_by_run.get(run_id) or {}).values())
        else:
            calls = list(_active_by_call.values())
    return [
        {
            "call_id": c.call_id,
            "run_id": c.run_id,
            "phase": c.phase,
            "started_at": c.started_at,
            "age_s": round(time.time() - c.started_at, 3),
            "task_done": c.task.done() if c.task is not None else True,
        }
        for c in calls
    ]


def active_coding_call_count(run_id: str | None = None) -> int:
    return len(active_coding_calls(run_id))


def broker_thread_name() -> str:
    return _BROKER_NAME


def _ensure_broker() -> asyncio.AbstractEventLoop:
    global _broker_loop, _broker_thread
    with _broker_lock:
        if _broker_thread is not None and _broker_thread.is_alive() and _broker_loop is not None:
            return _broker_loop

        _broker_ready.clear()

        def _run() -> None:
            global _broker_loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _broker_loop = loop
            _broker_ready.set()
            loop.run_forever()

        _broker_thread = threading.Thread(target=_run, name=_BROKER_NAME, daemon=True)
        _broker_thread.start()
    if not _broker_ready.wait(timeout=5.0):
        raise RuntimeError("coding_model_runtime_broker_start_failed")
    assert _broker_loop is not None
    return _broker_loop


def _register(call: _ActiveCall) -> None:
    with _registry_lock:
        _active_by_call[call.call_id] = call
        bucket = _active_by_run.setdefault(call.run_id, {})
        bucket[call.call_id] = call


def _unregister(call: _ActiveCall) -> None:
    with _registry_lock:
        _active_by_call.pop(call.call_id, None)
        bucket = _active_by_run.get(call.run_id)
        if bucket is not None:
            bucket.pop(call.call_id, None)
            if not bucket:
                _active_by_run.pop(call.run_id, None)
    call.done.set()


def _cancel_task_on_owner(call: _ActiveCall) -> None:
    task = call.task
    loop = call.loop
    if task is None or loop is None:
        return
    if task.done():
        return

    def _do_cancel() -> None:
        if not task.done():
            task.cancel()

    try:
        loop.call_soon_threadsafe(_do_cancel)
    except RuntimeError:
        # Loop closed — nothing left to cancel.
        pass


def cancel_coding_run(run_id: str | None, *, wait_s: float = 5.0) -> dict[str, Any]:
    """Fence run + cancel every active Coding model Task on its owner loop."""
    if not run_id:
        return {"ok": False, "run_id": run_id, "cancelled_calls": 0}
    fence_coding_run(run_id)
    with _registry_lock:
        calls = list((_active_by_run.get(run_id) or {}).values())
    for call in calls:
        _cancel_task_on_owner(call)
    # Observe termination without pretending Future.cancel kills a thread.
    deadline = time.monotonic() + max(0.0, float(wait_s))
    for call in calls:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        call.done.wait(timeout=remaining)
    return {
        "ok": True,
        "run_id": run_id,
        "cancelled_calls": len(calls),
        "active_remaining": active_coding_call_count(run_id),
    }


async def _await_call(
    *,
    call: _ActiveCall,
    coro_factory: Callable[[], Awaitable[Any]],
    timeout_s: float | None,
    cancel_check: Callable[[], bool] | None,
) -> CodingModelResult:
    # Cancel-before-register: fail closed before invoking provider.
    if is_coding_run_cancelled(call.run_id) or (callable(cancel_check) and cancel_check()):
        fence_coding_run(call.run_id)
        return CodingModelResult(
            kind="cancelled",
            call_id=call.call_id,
            run_id=call.run_id,
            phase=call.phase,
            error="cancel_before_register",
            meta={"fence": True, "underlying_cancelled": True},
        )

    loop = asyncio.get_running_loop()
    call.loop = loop
    provider_task: asyncio.Task[Any] = asyncio.create_task(coro_factory())
    call.task = provider_task
    _register(call)
    try:
        if is_coding_run_cancelled(call.run_id) or (callable(cancel_check) and cancel_check()):
            provider_task.cancel()
            try:
                await provider_task
            except (asyncio.CancelledError, Exception):
                pass
            return CodingModelResult(
                kind="cancelled",
                call_id=call.call_id,
                run_id=call.run_id,
                phase=call.phase,
                error="cancelled_at_register",
                meta={"fence": True, "underlying_cancelled": True},
            )

        if timeout_s is None:
            response = await provider_task
        else:
            try:
                # wait_for cancels provider_task on timeout; we then await unwind
                # so httpx AsyncClient context managers exit on this owner loop.
                response = await asyncio.wait_for(provider_task, timeout=float(timeout_s))
            except asyncio.TimeoutError:
                if not provider_task.done():
                    provider_task.cancel()
                try:
                    await provider_task
                except (asyncio.CancelledError, Exception):
                    pass
                return CodingModelResult(
                    kind="timeout",
                    call_id=call.call_id,
                    run_id=call.run_id,
                    phase=call.phase,
                    error=f"lm_invoke_timeout:{timeout_s}",
                    meta={
                        "timeout_s": float(timeout_s),
                        "underlying_cancelled": True,
                        "worker_ownership": "joined",
                    },
                )

        # Late-response fence: provider finished but run was cancelled in the race window.
        if is_coding_run_cancelled(call.run_id) or (callable(cancel_check) and cancel_check()):
            return CodingModelResult(
                kind="cancelled",
                call_id=call.call_id,
                run_id=call.run_id,
                phase=call.phase,
                error="late_response_fenced",
                meta={"late_fence": True, "underlying_cancelled": True},
            )
        return CodingModelResult(
            kind="ok",
            response=response,
            call_id=call.call_id,
            run_id=call.run_id,
            phase=call.phase,
            meta={"worker_ownership": "joined"},
        )
    except asyncio.CancelledError:
        if not provider_task.done():
            provider_task.cancel()
            try:
                await provider_task
            except (asyncio.CancelledError, Exception):
                pass
        return CodingModelResult(
            kind="cancelled",
            call_id=call.call_id,
            run_id=call.run_id,
            phase=call.phase,
            error="task_cancelled",
            meta={"underlying_cancelled": True, "worker_ownership": "joined"},
        )
    except Exception as exc:  # noqa: BLE001 — classified at boundary
        err = str(exc)
        if "geannuleerd" in err.lower() or "cancelled" in err.lower() or is_coding_run_cancelled(call.run_id):
            return CodingModelResult(
                kind="cancelled",
                call_id=call.call_id,
                run_id=call.run_id,
                phase=call.phase,
                error=err[:500],
                meta={"underlying_cancelled": True},
            )
        return CodingModelResult(
            kind="error",
            call_id=call.call_id,
            run_id=call.run_id,
            phase=call.phase,
            error=err[:500],
            meta={},
        )
    finally:
        _unregister(call)


async def ainvoke_coding_model(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    run_id: str | None = None,
    timeout_s: float | None = 120.0,
    phase: str = "model",
    cancel_check: Callable[[], bool] | None = None,
) -> CodingModelResult:
    """Async entry: run on the *current* event loop (owner = this loop)."""
    rid = str(run_id or "").strip() or new_coding_run_id(prefix="coding-ephemeral")
    call = _ActiveCall(
        call_id=f"cmc_{uuid.uuid4().hex[:12]}",
        run_id=rid,
        phase=phase,
        started_at=time.time(),
    )
    return await _await_call(
        call=call,
        coro_factory=coro_factory,
        timeout_s=timeout_s,
        cancel_check=cancel_check,
    )


def invoke_coding_model(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    run_id: str | None = None,
    timeout_s: float | None = 120.0,
    phase: str = "model",
    cancel_check: Callable[[], bool] | None = None,
) -> CodingModelResult:
    """Sync entry for Coding workers: submit to the dedicated broker loop."""
    rid = str(run_id or "").strip() or new_coding_run_id(prefix="coding-ephemeral")
    if is_coding_run_cancelled(rid) or (callable(cancel_check) and cancel_check()):
        fence_coding_run(rid)
        return CodingModelResult(
            kind="cancelled",
            run_id=rid,
            phase=phase,
            error="cancel_before_register",
            meta={"fence": True, "underlying_cancelled": True},
        )

    call = _ActiveCall(
        call_id=f"cmc_{uuid.uuid4().hex[:12]}",
        run_id=rid,
        phase=phase,
        started_at=time.time(),
    )
    loop = _ensure_broker()

    async def _runner() -> CodingModelResult:
        return await _await_call(
            call=call,
            coro_factory=coro_factory,
            timeout_s=timeout_s,
            cancel_check=cancel_check,
        )

    fut: concurrent.futures.Future[CodingModelResult] = asyncio.run_coroutine_threadsafe(_runner(), loop)
    # Outer wait must cover timeout + cleanup; Layer 1 already cancelled the Task.
    outer_timeout = None if timeout_s is None else float(timeout_s) + _CLEANUP_GRACE_S
    try:
        return fut.result(timeout=outer_timeout)
    except concurrent.futures.TimeoutError:
        _cancel_task_on_owner(call)
        call.done.wait(timeout=5.0)
        return CodingModelResult(
            kind="timeout",
            call_id=call.call_id,
            run_id=rid,
            phase=phase,
            error=f"lm_invoke_timeout:{timeout_s}",
            meta={
                "timeout_s": timeout_s,
                "underlying_cancelled": True,
                "worker_ownership": "broker_outer_timeout",
            },
        )


def invoke_coding_chat_fn(
    chat_fn: Any,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
    timeout_s: float | None = 120.0,
    phase: str = "model",
    cancel_check: Callable[[], bool] | None = None,
) -> CodingModelResult:
    """Invoke sync or async chat_fn through the Coding model lifecycle."""

    async def _coro() -> Any:
        result = chat_fn(payload)
        if inspect_isawaitable(result):
            return await result
        return result

    return invoke_coding_model(
        _coro,
        run_id=run_id,
        timeout_s=timeout_s,
        phase=phase,
        cancel_check=cancel_check,
    )


def inspect_isawaitable(value: Any) -> bool:
    return asyncio.iscoroutine(value) or asyncio.isfuture(value) or hasattr(value, "__await__")


def coding_broker_worker_count() -> int:
    """Count live threads that belong to the Coding LM broker."""
    name = _BROKER_NAME
    return sum(1 for t in threading.enumerate() if t.is_alive() and t.name == name)


# --- Legacy adapter used by coding_agent._invoke_chat_fn ---


def invoke_chat_fn_safe(
    chat_fn: Any,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    timeout_s: float | None = 120.0,
    run_id: str | None = None,
    phase: str = "model",
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    """Drop-in replacement for the old stranded ThreadPoolExecutor bridge."""
    outcome = invoke_coding_model(
        coro_factory,
        run_id=run_id,
        timeout_s=timeout_s,
        phase=phase,
        cancel_check=cancel_check,
    )
    meta = outcome.to_invoke_meta()
    if outcome.kind == "ok":
        return outcome.response, meta
    return None, meta
