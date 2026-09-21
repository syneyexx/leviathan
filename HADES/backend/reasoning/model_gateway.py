"""Shared model call gateway: capacity, retries, metrics, typed errors.

All Chat / Work / Coding / Committee / Eval LM calls should go through
``ModelGateway.chat`` (or ``chat_stream``) so concurrency ceilings are shared.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Callable, Literal


class ModelGatewayError(RuntimeError):
    """Base typed gateway error."""

    code: str = "gateway_error"

    def __init__(self, message: str, *, code: str | None = None, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.detail = dict(detail or {})


class ModelCapacityTimeout(ModelGatewayError):
    code = "capacity_timeout"


class ModelCallCancelled(ModelGatewayError):
    code = "cancelled"


class ModelCallFailed(ModelGatewayError):
    code = "call_failed"


class ModelRetriesExhausted(ModelGatewayError):
    code = "retries_exhausted"


FallbackReason = Literal[
    "unavailable",
    "timeout",
    "error",
    "capacity",
    "capability_missing",
    "explicit",
    "",
]


@dataclass(slots=True)
class GatewayConfigSnapshot:
    """Scoped config for one run — frozen at start so live setting edits do not mutate mid-call policy."""

    global_limit: int | None = 1
    endpoint_limit: int | None = 1
    max_retries: int = 1
    retry_backoff_s: float = 0.25
    acquire_timeout_s: float | None = 60.0
    request_timeout_s: float | None = 120.0
    endpoint: str = ""
    source: str = "runtime"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _ActiveCall:
    call_id: str
    model_id: str
    endpoint: str
    surface: str
    started_at: float
    run_id: str | None = None


@dataclass
class ModelGateway:
    """Process-wide capacity + metrics around an async chat callable."""

    global_limit: int | None = 1
    endpoint_limits: dict[str, int | None] = field(default_factory=dict)
    max_retries: int = 1
    retry_backoff_s: float = 0.25
    acquire_timeout_s: float | None = 60.0

    _global_inflight: int = 0
    _global_waiters: int = 0
    _endpoint_inflight: dict[str, int] = field(default_factory=dict)
    _endpoint_waiters: dict[str, int] = field(default_factory=dict)
    _active: dict[str, _ActiveCall] = field(default_factory=dict)
    _cond: asyncio.Condition | None = field(default=None, repr=False)
    _metrics: dict[str, Any] = field(
        default_factory=lambda: {
            "calls_started": 0,
            "calls_succeeded": 0,
            "calls_failed": 0,
            "calls_cancelled": 0,
            "retries": 0,
            "capacity_timeouts": 0,
            "last_error": None,
            "last_fallback_reason": None,
            "last_model_id": None,
            "last_runtime": None,
        }
    )
    _lock_init: asyncio.Lock | None = field(default=None, repr=False)

    def _ensure_cond(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    def configure(
        self,
        *,
        global_limit: int | None | object = ...,
        endpoint: str | None = None,
        endpoint_limit: int | None | object = ...,
        max_retries: int | None = None,
        retry_backoff_s: float | None = None,
        acquire_timeout_s: float | None | object = ...,
    ) -> None:
        """Update live limits without dropping waiters or resetting in-flight counts.

        ``None`` means Unlimited (product semantic) — never translated to a huge int.
        """
        if global_limit is not ...:
            self.global_limit = None if global_limit is None else max(0, int(global_limit))
        if endpoint is not None and endpoint_limit is not ...:
            self.endpoint_limits[endpoint] = None if endpoint_limit is None else max(0, int(endpoint_limit))
        if max_retries is not None:
            self.max_retries = max(0, int(max_retries))
        if retry_backoff_s is not None:
            self.retry_backoff_s = max(0.0, float(retry_backoff_s))
        if acquire_timeout_s is not ...:
            self.acquire_timeout_s = None if acquire_timeout_s is None else float(acquire_timeout_s)
        # Wake waiters so they re-check against the new limit (e.g. raised capacity).
        self._notify_waiters()

    def _notify_waiters(self) -> None:
        cond = self._cond
        if cond is None:
            return

        def _ping() -> None:
            # Prefer notifying under the lock when already on the loop.
            try:
                if cond.locked():
                    cond.notify_all()
                else:
                    # Best-effort: schedule an async notify on the running loop.
                    async def _notify() -> None:
                        async with cond:
                            cond.notify_all()

                    asyncio.get_running_loop().create_task(_notify())
            except RuntimeError:
                pass

        try:
            loop = asyncio.get_running_loop()
            # Wake immediately when possible; also schedule for waiters mid-await.
            loop.call_soon(_ping)
            async def _notify() -> None:
                async with cond:
                    cond.notify_all()

            loop.create_task(_notify())
        except RuntimeError:
            pass

    def snapshot_config(self, *, endpoint: str = "", source: str = "runtime") -> GatewayConfigSnapshot:
        ep_limit = self.endpoint_limits.get(endpoint, self.global_limit)
        return GatewayConfigSnapshot(
            global_limit=self.global_limit,
            endpoint_limit=ep_limit,
            max_retries=self.max_retries,
            retry_backoff_s=self.retry_backoff_s,
            acquire_timeout_s=self.acquire_timeout_s,
            endpoint=endpoint,
            source=source,
        )

    def _ep_key(self, endpoint: str, model_id: str) -> str:
        return f"{endpoint}::{model_id}"

    def _can_enter(self, key: str, *, global_limit: int | None, endpoint_limit: int | None) -> bool:
        if global_limit is not None and self._global_inflight >= int(global_limit):
            return False
        if endpoint_limit is not None and self._endpoint_inflight.get(key, 0) >= int(endpoint_limit):
            return False
        return True

    async def acquire(
        self,
        model_id: str,
        *,
        endpoint: str,
        config: GatewayConfigSnapshot | None = None,
        cancel_event: asyncio.Event | None = None,
        surface: str = "unknown",
        run_id: str | None = None,
    ) -> str:
        cfg = config or self.snapshot_config(endpoint=endpoint)
        key = self._ep_key(endpoint, model_id)
        cond = self._ensure_cond()
        deadline = None if cfg.acquire_timeout_s is None else time.monotonic() + float(cfg.acquire_timeout_s)
        wait_started = time.perf_counter()
        async with cond:
            self._global_waiters += 1
            self._endpoint_waiters[key] = self._endpoint_waiters.get(key, 0) + 1
            try:
                while not self._can_enter(
                    key,
                    # Always re-check live process limits so configure() can unblock waiters.
                    global_limit=self.global_limit,
                    endpoint_limit=self.endpoint_limits.get(endpoint, self.global_limit),
                ):
                    if cancel_event is not None and cancel_event.is_set():
                        raise ModelCallCancelled("Model call cancelled while waiting for capacity.")
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self._metrics["capacity_timeouts"] = int(self._metrics.get("capacity_timeouts") or 0) + 1
                            raise ModelCapacityTimeout(
                                "Timed out waiting for model capacity.",
                                detail={"model_id": model_id, "endpoint": endpoint, "surface": surface},
                            )
                        try:
                            await asyncio.wait_for(cond.wait(), timeout=remaining)
                        except asyncio.TimeoutError:
                            self._metrics["capacity_timeouts"] = int(self._metrics.get("capacity_timeouts") or 0) + 1
                            raise ModelCapacityTimeout(
                                "Timed out waiting for model capacity.",
                                detail={"model_id": model_id, "endpoint": endpoint, "surface": surface},
                            ) from None
                    else:
                        await cond.wait()
                self._global_inflight += 1
                self._endpoint_inflight[key] = self._endpoint_inflight.get(key, 0) + 1
                call_id = f"mgw_{uuid.uuid4().hex[:12]}"
                self._active[call_id] = _ActiveCall(
                    call_id=call_id,
                    model_id=model_id,
                    endpoint=endpoint,
                    surface=surface,
                    started_at=time.time(),
                    run_id=run_id,
                )
                self._metrics["calls_started"] = int(self._metrics.get("calls_started") or 0) + 1
                self._metrics["last_model_id"] = model_id
                try:
                    from perf import record_model_call

                    record_model_call(queue_wait_ms=(time.perf_counter() - wait_started) * 1000)
                except Exception:
                    pass
                return call_id
            finally:
                self._global_waiters = max(0, self._global_waiters - 1)
                self._endpoint_waiters[key] = max(0, self._endpoint_waiters.get(key, 0) - 1)

    async def release(self, call_id: str | None, *, model_id: str = "", endpoint: str = "") -> None:
        cond = self._ensure_cond()
        async with cond:
            active = self._active.pop(call_id, None) if call_id else None
            if active is not None:
                key = self._ep_key(active.endpoint, active.model_id)
            else:
                key = self._ep_key(endpoint, model_id) if model_id else ""
            self._global_inflight = max(0, self._global_inflight - 1)
            if key:
                self._endpoint_inflight[key] = max(0, self._endpoint_inflight.get(key, 0) - 1)
            cond.notify_all()

    @asynccontextmanager
    async def slot(
        self,
        model_id: str,
        *,
        endpoint: str,
        config: GatewayConfigSnapshot | None = None,
        cancel_event: asyncio.Event | None = None,
        surface: str = "unknown",
        run_id: str | None = None,
    ) -> AsyncIterator[str]:
        call_id = await self.acquire(
            model_id,
            endpoint=endpoint,
            config=config,
            cancel_event=cancel_event,
            surface=surface,
            run_id=run_id,
        )
        try:
            yield call_id
        finally:
            await self.release(call_id)

    async def chat(
        self,
        chat_fn: Callable[..., Any],
        payload: dict[str, Any],
        *,
        model_id: str | None = None,
        endpoint: str = "",
        surface: str = "chat",
        run_id: str | None = None,
        config: GatewayConfigSnapshot | None = None,
        cancel_event: asyncio.Event | None = None,
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        mid = str(model_id or payload.get("model") or "").strip() or "unknown"
        cfg = config or self.snapshot_config(endpoint=endpoint, source=surface)
        if fallback_reason:
            self._metrics["last_fallback_reason"] = fallback_reason
        attempts = 0
        last_exc: BaseException | None = None
        max_attempts = 1 + max(0, int(cfg.max_retries))
        while attempts < max_attempts:
            attempts += 1
            if cancel_event is not None and cancel_event.is_set():
                self._metrics["calls_cancelled"] = int(self._metrics.get("calls_cancelled") or 0) + 1
                raise ModelCallCancelled("Model call cancelled before invoke.")
            try:
                async with self.slot(
                    mid,
                    endpoint=endpoint or cfg.endpoint,
                    config=cfg,
                    cancel_event=cancel_event,
                    surface=surface,
                    run_id=run_id,
                ):
                    result = chat_fn(payload)
                    if asyncio.iscoroutine(result):
                        response = await result
                    else:
                        response = result
                    self._metrics["calls_succeeded"] = int(self._metrics.get("calls_succeeded") or 0) + 1
                    # Optional runtime metadata recorded when callers attach it.
                    if isinstance(response, dict) and isinstance(response.get("_hades_runtime"), dict):
                        self._metrics["last_runtime"] = dict(response["_hades_runtime"])
                    return response  # type: ignore[no-any-return]
            except (ModelCapacityTimeout, ModelCallCancelled):
                raise
            except asyncio.CancelledError:
                self._metrics["calls_cancelled"] = int(self._metrics.get("calls_cancelled") or 0) + 1
                raise ModelCallCancelled("Model call cancelled.") from None
            except Exception as exc:  # noqa: BLE001 — typed wrap for callers
                last_exc = exc
                self._metrics["last_error"] = str(exc)[:500]
                self._metrics["calls_failed"] = int(self._metrics.get("calls_failed") or 0) + 1
                if attempts >= max_attempts:
                    break
                self._metrics["retries"] = int(self._metrics.get("retries") or 0) + 1
                await asyncio.sleep(cfg.retry_backoff_s * attempts)
        raise ModelRetriesExhausted(
            f"Model call failed after {attempts} attempt(s): {last_exc}",
            detail={"model_id": mid, "surface": surface},
        ) from last_exc

    def overview(self) -> dict[str, Any]:
        """Compact visible overview — no invented VRAM/quality metrics."""
        active = [
            {
                "call_id": item.call_id,
                "model_id": item.model_id,
                "endpoint": item.endpoint,
                "surface": item.surface,
                "run_id": item.run_id,
                "started_at": item.started_at,
                "age_s": round(time.time() - item.started_at, 2),
            }
            for item in self._active.values()
        ]
        models_in_use = sorted({item["model_id"] for item in active})
        queue_depth = self._global_waiters + sum(self._endpoint_waiters.values())
        return {
            "models_in_use": models_in_use,
            "active_calls": active,
            "active_count": len(active),
            "queue_depth": queue_depth,
            "capacity": {
                "global_limit": self.global_limit,
                "global_inflight": self._global_inflight,
                "global_waiters": self._global_waiters,
                "endpoint_limits": dict(self.endpoint_limits),
                "endpoint_inflight": dict(self._endpoint_inflight),
                "endpoint_waiters": dict(self._endpoint_waiters),
            },
            "fallback_reason": self._metrics.get("last_fallback_reason"),
            "last_runtime": self._metrics.get("last_runtime"),
            "errors": {
                "last_error": self._metrics.get("last_error"),
                "calls_failed": self._metrics.get("calls_failed"),
                "capacity_timeouts": self._metrics.get("capacity_timeouts"),
                "calls_cancelled": self._metrics.get("calls_cancelled"),
            },
            "metrics": dict(self._metrics),
        }


# Process-wide gateway (tests may replace / reconfigure).
model_gateway = ModelGateway()
