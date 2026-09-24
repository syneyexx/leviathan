"""Control-plane facade — submit/await/stream provider work without owning HTTP."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Iterator

from Data.modules.jobs.states import JobState, TERMINAL_JOB_STATES
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.policy import ProviderIoSettings
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import ProviderExecutionResult, StreamEvent
from Data.modules.workers.pools import pool_for_capability


_CLIENT_LOCK = threading.Lock()
_CLIENT: ProviderExecutionClient | None = None


class ProviderExecutionClient:
    """Thin control-plane client that enqueues provider_io jobs and awaits results."""

    def __init__(
        self,
        job_runtime: Any,
        *,
        stream_store: ProviderStreamStore | None = None,
        settings: ProviderIoSettings | None = None,
    ) -> None:
        self.job_runtime = job_runtime
        self.settings = settings or ProviderIoSettings.load()
        db_path = getattr(getattr(job_runtime, "store", None), "path", None)
        self.stream_store = stream_store or ProviderStreamStore(
            db_path or "Data/state/leviathan.db",
            max_events_per_job=self.settings.max_buffered_stream_events,
        )
        try:
            self.stream_store.initialize()
        except Exception:  # noqa: BLE001
            pass

    def _queue_depth(self) -> int:
        store = self.job_runtime.store
        try:
            queued = store.list(state=JobState.QUEUED, limit=self.settings.queue_capacity + 1)
            return sum(1 for j in queued if getattr(j, "worker_pool", None) == "provider_io")
        except Exception:  # noqa: BLE001
            return 0

    def submit(
        self,
        *,
        provider: str,
        capability: str,
        payload: dict[str, Any] | None = None,
        model: str | None = None,
        streaming: bool = False,
        credential_ref: str | None = None,
        correlation_id: str | None = None,
        principal_ref: str | None = None,
        idempotency_key: str | None = None,
        idempotency_class: str = "READ",
        deadline_seconds: float | None = None,
        allow_private_hosts: bool = False,
        latency_class: str = "interactive",
        priority: int | None = None,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        depth = self._queue_depth()
        if depth >= self.settings.queue_capacity:
            raise ProviderError(
                ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED,
                "Provider execution capacity is saturated.",
                provider=provider,
                retryable=True,
            )

        # Map capability id for pool routing.
        if capability.startswith("provider."):
            cap_id = capability
        else:
            cap_id = f"provider.{capability}"

        # Prefer exact registered capabilities.
        known = {
            "provider.http",
            "provider.chat.complete",
            "provider.chat.stream",
            "provider.market.fetch",
            "provider.hf.list",
        }
        if cap_id not in known:
            # Keep provider.<capability> for pool prefix match.
            pass

        arguments: dict[str, Any] = {
            "provider": provider,
            "capability": capability.replace("provider.", "", 1)
            if capability.startswith("provider.")
            else capability,
            "payload": dict(payload or {}),
            "streaming": streaming,
            "credential_ref": credential_ref,
            "correlation_id": correlation_id,
            "principal_ref": principal_ref,
            "idempotency_class": idempotency_class,
            "allow_private_hosts": allow_private_hosts,
        }
        if model is not None:
            arguments["model"] = model
        if deadline_seconds is not None:
            arguments["deadline_seconds"] = float(deadline_seconds)

        worker_pool = pool_for_capability(cap_id)
        return self.job_runtime.enqueue(
            capability_id=cap_id if cap_id in known else "provider.http",
            arguments=arguments,
            requested_by=requested_by,
            metadata=metadata,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            latency_class=latency_class,
            worker_pool=worker_pool or "provider_io",
            resource_class="NETWORK_BOUND",
            priority=priority if priority is not None else (10 if latency_class == "interactive" else 50),
            timeout_seconds=deadline_seconds or self.settings.total_deadline_seconds,
            domain="provider_io",
            consumer="provider_execution",
        )

    def await_result(
        self,
        job_id: str,
        *,
        poll_seconds: float = 0.05,
        timeout_seconds: float | None = None,
    ) -> ProviderExecutionResult:
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else self.settings.total_deadline_seconds + 30.0
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.job_runtime.get(job_id)
            if job is None:
                raise KeyError(f"Unknown job: {job_id}")
            if job.state in TERMINAL_JOB_STATES:
                raw = job.result if isinstance(job.result, dict) else {}
                if job.state == JobState.COMPLETED:
                    return ProviderExecutionResult(
                        status=str(raw.get("status") or "succeeded"),
                        content=raw.get("content"),
                        tool_calls=list(raw.get("tool_calls") or []),
                        structured=raw.get("structured"),
                        finish_reason=raw.get("finish_reason"),
                        usage=dict(raw.get("usage") or {}),
                        provider=raw.get("provider"),
                        model=raw.get("model"),
                        provider_request_id=raw.get("provider_request_id"),
                        timing=dict(raw.get("timing") or {}),
                        error=raw.get("error"),
                        metadata=dict(raw.get("metadata") or {}),
                        worker_pid=raw.get("worker_pid"),
                    )
                if job.state == JobState.CANCELLED:
                    return ProviderExecutionResult(
                        status="cancelled",
                        error=raw.get("error")
                        or {"code": "EXECUTION_CANCELLED", "message": job.error},
                        worker_pid=raw.get("worker_pid") if isinstance(raw, dict) else None,
                    )
                err = raw.get("error") if isinstance(raw, dict) else None
                return ProviderExecutionResult(
                    status="failed",
                    error=err or {"code": job.error or "PROVIDER_UNKNOWN", "message": job.error},
                    worker_pid=raw.get("worker_pid") if isinstance(raw, dict) else None,
                    provider=raw.get("provider") if isinstance(raw, dict) else None,
                )
            time.sleep(poll_seconds)
        raise ProviderError(
            ProviderErrorCode.PROVIDER_TIMEOUT,
            f"Timed out waiting for provider job {job_id}",
            retryable=False,
        )

    def submit_and_wait(self, **kwargs: Any) -> ProviderExecutionResult:
        job = self.submit(**kwargs)
        return self.await_result(
            job.job_id,
            timeout_seconds=kwargs.get("deadline_seconds"),
        )

    def iter_stream(self, job_id: str, *, after_sequence: int = 0) -> Iterator[StreamEvent]:
        timeout = self.settings.total_deadline_seconds + 30.0
        yield from self.stream_store.iter_until_terminal(
            job_id,
            after_sequence=after_sequence,
            timeout_seconds=timeout,
        )

    def cancel(self, job_id: str, *, reason: str | None = None) -> Any:
        return self.job_runtime.cancel(job_id, reason=reason or "provider_client_cancel")


def get_provider_client(job_runtime: Any | None = None) -> ProviderExecutionClient:
    """Process-wide facade for the API process (not for worker processes)."""
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None and (
            job_runtime is None or _CLIENT.job_runtime is job_runtime
        ):
            return _CLIENT
        if job_runtime is None:
            raise RuntimeError("ProviderExecutionClient requires job_runtime on first use")
        _CLIENT = ProviderExecutionClient(job_runtime)
        return _CLIENT


def control_plane_pid() -> int:
    return os.getpid()
