"""Control-plane facade — submit/await/cancel model_runtime jobs without owning processes."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from Data.modules.jobs.states import TERMINAL_JOB_STATES
from Data.modules.model_runtime.readiness import model_runtime_workers_ready
from Data.modules.models.errors import (
    MODEL_RUNTIME_UNAVAILABLE,
    ModelControlError,
)
from Data.modules.workers.pools import pool_for_capability


_CLIENT_LOCK = threading.Lock()
_CLIENT: ModelRuntimeClient | None = None

CAP_LOAD = "model_runtime.load"
CAP_UNLOAD = "model_runtime.unload"
CAP_RECONCILE = "model_runtime.reconcile"
CAP_BENCHMARK = "model_runtime.benchmark"
CAP_PROBE = "model_runtime.probe"
CAP_INFERENCE_TEST = "model_runtime.inference_test"

ALL_CAPS = frozenset(
    {CAP_LOAD, CAP_UNLOAD, CAP_RECONCILE, CAP_BENCHMARK, CAP_PROBE, CAP_INFERENCE_TEST}
)


class ModelRuntimeClient:
    """Thin control-plane client that enqueues model_runtime singleton jobs."""

    def __init__(self, job_runtime: Any) -> None:
        self.job_runtime = job_runtime

    def _db_path(self) -> Any:
        return getattr(getattr(self.job_runtime, "store", None), "path", None)

    def require_workers_ready(self) -> None:
        if not model_runtime_workers_ready(self._db_path()):
            raise ModelControlError(
                code=MODEL_RUNTIME_UNAVAILABLE,
                message=(
                    "Model runtime worker is unavailable; Control Plane will not "
                    "start managed servers or run inference diagnostics inline."
                ),
                retryable=True,
                http_status=503,
            )

    def _enqueue(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        requested_by: str = "api",
        idempotency_key: str | None = None,
        latency_class: str = "background",
        resource_class: str = "CPU_LIGHT",
        priority: int = 60,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        self.require_workers_ready()
        worker_pool = pool_for_capability(capability_id) or "model_runtime"
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("LEVIATHAN_MODEL_RUNTIME_JOB_TIMEOUT") or 0)
            or 1800.0
        )
        return self.job_runtime.enqueue(
            capability_id=capability_id,
            arguments=arguments,
            requested_by=requested_by,
            metadata=metadata,
            idempotency_key=idempotency_key,
            latency_class=latency_class,
            worker_pool=worker_pool,
            resource_class=resource_class,
            priority=priority,
            timeout_seconds=timeout,
            domain="model_runtime",
            consumer="model_runtime",
        )

    def submit_load(
        self,
        *,
        model_id: str,
        options: dict[str, Any] | None = None,
        confirm_oom: bool = False,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        args: dict[str, Any] = {
            "model_id": model_id,
            "options": dict(options or {}),
            "confirm_oom": bool(confirm_oom),
        }
        # Idempotent for same model + option fingerprint.
        opt_fp = _options_fingerprint(args["options"])
        return self._enqueue(
            CAP_LOAD,
            args,
            requested_by=requested_by,
            idempotency_key=f"model_runtime.load:{model_id}:{opt_fp}",
            latency_class="interactive",
            resource_class="MODEL_INFERENCE",
            priority=40,
            metadata=metadata,
        )

    def submit_unload(
        self,
        *,
        model_id: str,
        serving_generation: int | None = None,
        force: bool = False,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        args: dict[str, Any] = {
            "model_id": model_id,
            "force": bool(force),
        }
        if serving_generation is not None:
            args["serving_generation"] = int(serving_generation)
        gen = serving_generation if serving_generation is not None else "any"
        return self._enqueue(
            CAP_UNLOAD,
            args,
            requested_by=requested_by,
            idempotency_key=f"model_runtime.unload:{model_id}:{gen}",
            latency_class="interactive",
            resource_class="CPU_LIGHT",
            priority=35,
            metadata=metadata,
        )

    def submit_reconcile(
        self,
        *,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self._enqueue(
            CAP_RECONCILE,
            {},
            requested_by=requested_by,
            idempotency_key=f"model_runtime.reconcile:{int(time.time() // 30)}",
            latency_class="background",
            resource_class="CPU_LIGHT",
            priority=90,
            timeout_seconds=120.0,
            metadata=metadata,
        )

    def submit_benchmark(
        self,
        *,
        model_id: str,
        warmup: int = 1,
        iterations: int = 3,
        prompt: str | None = None,
        max_tokens: int = 16,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        args: dict[str, Any] = {
            "model_id": model_id,
            "warmup": max(0, int(warmup)),
            "iterations": max(1, min(int(iterations), 20)),
            "max_tokens": max(1, min(int(max_tokens), 256)),
        }
        if prompt:
            args["prompt"] = str(prompt)[:500]
        return self._enqueue(
            CAP_BENCHMARK,
            args,
            requested_by=requested_by,
            latency_class="batch",
            resource_class="MODEL_INFERENCE",
            priority=120,
            metadata=metadata,
        )

    def submit_probe(
        self,
        *,
        model_id: str,
        capabilities: list[str] | None = None,
        timeout_seconds: float = 15.0,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        args: dict[str, Any] = {
            "model_id": model_id,
            "timeout_seconds": float(timeout_seconds),
        }
        if capabilities:
            args["capabilities"] = list(capabilities)
        caps_key = ",".join(sorted(capabilities or ["default"]))
        return self._enqueue(
            CAP_PROBE,
            args,
            requested_by=requested_by,
            idempotency_key=f"model_runtime.probe:{model_id}:{caps_key}:{int(timeout_seconds)}",
            latency_class="background",
            resource_class="MODEL_INFERENCE",
            priority=100,
            metadata=metadata,
        )

    def submit_inference_test(
        self,
        *,
        model_id: str,
        prompt: str = "ping",
        max_tokens: int = 64,
        stream: bool = False,
        requested_by: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        args: dict[str, Any] = {
            "model_id": model_id,
            "prompt": str(prompt)[:2000],
            "max_tokens": max(1, min(int(max_tokens), 512)),
            "stream": bool(stream),
        }
        return self._enqueue(
            CAP_INFERENCE_TEST,
            args,
            requested_by=requested_by,
            latency_class="background",
            resource_class="MODEL_INFERENCE",
            priority=80,
            metadata=metadata,
        )

    def cancel(self, job_id: str, *, reason: str | None = None) -> Any:
        return self.job_runtime.cancel(job_id, reason=reason or "model_runtime_cancel")

    def await_terminal(
        self,
        job_id: str,
        *,
        poll_seconds: float = 0.1,
        timeout_seconds: float | None = None,
    ) -> Any:
        timeout = float(timeout_seconds if timeout_seconds is not None else 30.0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.job_runtime.get(job_id)
            if job is None:
                raise KeyError(f"Unknown job: {job_id}")
            if job.state in TERMINAL_JOB_STATES:
                return job
            time.sleep(poll_seconds)
        raise ModelControlError(
            code=MODEL_RUNTIME_UNAVAILABLE,
            message=f"Timed out waiting for model_runtime job {job_id}",
            retryable=True,
            http_status=504,
        )


def _options_fingerprint(options: dict[str, Any]) -> str:
    import hashlib
    import json

    raw = json.dumps(options, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def get_model_runtime_client(job_runtime: Any | None = None) -> ModelRuntimeClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None and (
            job_runtime is None or _CLIENT.job_runtime is job_runtime
        ):
            return _CLIENT
        if job_runtime is None:
            raise RuntimeError("ModelRuntimeClient requires job_runtime on first use")
        _CLIENT = ModelRuntimeClient(job_runtime)
        return _CLIENT


def reset_model_runtime_client_for_tests() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None
