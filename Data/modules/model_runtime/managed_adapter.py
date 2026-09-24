"""Managed local OpenAI-compatible serving adapter (vLLM-class / llama.cpp path).

Reports measured capabilities to the Model Control Plane. Does not create a
second registry or job database (U021–U024).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncIterator

from Data.modules.model_runtime.latency import LatencyTimer
from Data.modules.model_runtime.serving import (
    ServingSupervisor,
    ServingWorker,
    StreamCancelToken,
    WorkerState,
    get_serving_supervisor,
)
from Data.modules.models.contracts import (
    CapabilityState,
    LoadOptions,
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
    ProviderHealth,
    RuntimeCapabilities,
)
from Data.modules.models.errors import (
    CAPABILITY_NOT_SUPPORTED,
    MODEL_LOAD_FAILED,
    ModelControlError,
)


class ManagedLocalServingAdapter:
    """Adapter boundary for managed local serving backends.

    When ``mode='inproc'`` AND ``allow_inproc_fixture=True`` (tests only),
    load/unload/stream are simulated honestly in-process.
    Production without a binary → UNAVAILABLE, never fake READY.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        backend_kind: str = "vllm_class",
        endpoint: str = "http://127.0.0.1:8000/v1",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        mode: str = "inproc",
        command: list[str] | None = None,
        supervisor: ServingSupervisor | None = None,
        allow_inproc_fixture: bool = False,
    ) -> None:
        self.provider_id = provider_id
        self.backend_kind = backend_kind
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.command = list(command or [])
        self.allow_inproc_fixture = bool(allow_inproc_fixture)
        # Prefer subprocess when a command is configured; otherwise inproc only if allowed.
        if self.command:
            self.mode = "subprocess"
        elif mode == "inproc" and self.allow_inproc_fixture:
            self.mode = "inproc"
        elif mode == "subprocess":
            self.mode = "subprocess"
        else:
            # No command and fixture not allowed → subprocess with empty command → UNAVAILABLE
            self.mode = "subprocess"
        self.supervisor = supervisor or get_serving_supervisor()
        self._model_to_worker: dict[str, str] = {}
        self._capabilities = RuntimeCapabilities(
            discover_models=True,
            import_model=False,
            download_model=False,
            load_model=True,
            unload_model=True,
            delete_model=False,
            list_loaded_models=True,
            inference=True,
            streaming=True,
            embeddings=False,
            tool_calling=False,
            structured_output=False,
            vision=False,
            runtime_metrics=True,
            load_options=(
                "contextLength",
                "gpuOffloadLayers",
                "gpuMemoryLimitBytes",
                "cpuThreads",
                "batchSize",
            ),
        )

    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

    async def health(self) -> tuple[ProviderHealth, float | None, str | None]:
        workers = [
            w
            for w in self.supervisor.list_workers()
            if w.provider_id == self.provider_id
        ]
        if not workers:
            return ProviderHealth.UNKNOWN, None, "no managed workers started"
        ready = [w for w in workers if w.state == WorkerState.READY]
        if ready:
            scores = [w.health_score for w in ready if w.health_score is not None]
            avg = sum(scores) / len(scores) if scores else None
            return ProviderHealth.HEALTHY, None, f"{len(ready)} ready worker(s); score={avg}"
        dead = [w for w in workers if w.state == WorkerState.DEAD]
        if dead:
            return ProviderHealth.OFFLINE, None, dead[-1].last_error or "worker dead"
        unavailable = [w for w in workers if w.state == WorkerState.UNAVAILABLE]
        if unavailable:
            return (
                ProviderHealth.OFFLINE,
                None,
                unavailable[-1].last_error or "serving unavailable",
            )
        return ProviderHealth.DEGRADED, None, "workers present but not ready"

    async def discover(self) -> list[ModelDescriptor]:
        # Managed adapters do not invent remote catalogs; loaded residency only.
        out: list[ModelDescriptor] = []
        for worker in self.supervisor.list_workers():
            if worker.provider_id != self.provider_id:
                continue
            if worker.state not in (WorkerState.READY, WorkerState.DRAINING):
                continue
            out.append(
                ModelDescriptor(
                    id=worker.model_id,
                    display_name=worker.model_id,
                    provider_id=self.provider_id,
                    source=ModelSource.LOCAL,
                    capabilities=ModelCapabilities(
                        chat=CapabilityState.SUPPORTED,
                        streaming=CapabilityState.SUPPORTED,
                    ),
                    lifecycle_state=ModelLifecycleState.LOADED,
                    health=ModelHealthState.HEALTHY,
                    loaded=True,
                    runtime_id=self.backend_kind,
                    format="managed",
                    family=self.backend_kind,
                    metadata={
                        "worker_id": worker.worker_id,
                        "revision_id": worker.revision_id,
                        "managed": True,
                    },
                )
            )
        return out

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        _ = options
        existing = self._model_to_worker.get(model_id)
        if existing:
            worker = self.supervisor.get_worker(existing)
            if worker and worker.state == WorkerState.READY:
                return {
                    "worker": worker.public_dict(),
                    "alreadyLoaded": True,
                    "truth": {"managed_serving": True},
                }

        if self.mode == "inproc":
            if not self.allow_inproc_fixture:
                raise ModelControlError(
                    code=CAPABILITY_NOT_SUPPORTED,
                    message=(
                        "inproc fixture is not allowed in production; "
                        "configure a managed serving binary or enable allow_inproc_fixture for tests"
                    ),
                    provider_id=self.provider_id,
                    model_id=model_id,
                    http_status=409,
                )
            worker = self.supervisor.start_inproc(
                provider_id=self.provider_id,
                model_id=model_id,
                revision_id=f"{self.backend_kind}:{model_id}",
                endpoint=self.endpoint if self.endpoint.startswith("inproc") else "inproc://local",
                backend_kind=self.backend_kind,
            )
        else:
            worker = await asyncio.to_thread(
                self.supervisor.start_subprocess,
                provider_id=self.provider_id,
                model_id=model_id,
                backend_kind=self.backend_kind,
                command=self.command,
                endpoint=self.endpoint,
                revision_id=f"{self.backend_kind}:{model_id}",
            )

        self._model_to_worker[model_id] = worker.worker_id
        if worker.state == WorkerState.UNAVAILABLE:
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message=worker.last_error or "managed serving unavailable",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
                details=worker.public_dict(),
            )
        if worker.state == WorkerState.DEAD:
            raise ModelControlError(
                code=MODEL_LOAD_FAILED,
                message=worker.last_error or "serving worker died during start",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=500,
                details=worker.public_dict(),
            )
        if worker.state not in (WorkerState.READY, WorkerState.STARTING):
            raise ModelControlError(
                code=MODEL_LOAD_FAILED,
                message=f"worker not ready: {worker.state.value}",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=503,
                details=worker.public_dict(),
            )
        return {
            "worker": worker.public_dict(),
            "alreadyLoaded": False,
            "truth": {"managed_serving": True, "dead_is_not_ready": True},
        }

    async def unload(self, model_id: str) -> dict[str, Any]:
        worker_id = self._model_to_worker.pop(model_id, None)
        if worker_id is None:
            # Best-effort: find by model
            for worker in self.supervisor.workers_for_model(model_id):
                if worker.provider_id == self.provider_id:
                    worker_id = worker.worker_id
                    break
        if worker_id is None:
            return {"unloaded": False, "detail": "no worker for model"}
        worker = self.supervisor.stop(worker_id, drain=True)
        return {"unloaded": True, "worker": worker.public_dict()}

    async def remove(self, model_id: str) -> None:
        await self.unload(model_id)

    async def test_inference(
        self,
        model_id: str,
        *,
        prompt: str = "ping",
        max_tokens: int = 8,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        worker_id = self._model_to_worker.get(model_id)
        worker = self.supervisor.get_worker(worker_id) if worker_id else None
        if worker is None or worker.state != WorkerState.READY:
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="model not loaded in managed serving worker",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )
        timer = LatencyTimer()
        timer.mark_admitted()
        # Inproc: deterministic echo — not a fabricated quality score.
        text = f"pong:{prompt[:max_tokens]}"
        timer.mark_first_token()
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="inference timeout",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=408,
            )
        latency = timer.finish(source="inproc_fixture")
        return {
            "ok": True,
            "output": text,
            "content": text,
            "preview": text,
            "model_id": model_id,
            "revision_id": worker.revision_id,
            "streaming": False,
            "latencyMs": latency.total_ms,
            "latency": latency.public_dict(),
            "truth": {
                "fixture_inference": worker.backend_kind == "inproc",
                "unmeasured_quality": True,
                "stages_are_separated": True,
            },
        }

    async def stream_tokens(
        self,
        model_id: str,
        *,
        prompt: str,
        cancel: StreamCancelToken | None = None,
        max_tokens: int = 32,
        timeout_seconds: float | None = None,
        token_delay_seconds: float = 0.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """True token stream with cancel + timeout (U025 / Round 6). Never fakes SSE from full text."""
        worker_id = self._model_to_worker.get(model_id)
        worker = self.supervisor.get_worker(worker_id) if worker_id else None
        if worker is None or worker.state != WorkerState.READY:
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="model not loaded for streaming",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )
        timer = LatencyTimer()
        timer.mark_admitted()
        deadline = (
            time.perf_counter() + timeout_seconds if timeout_seconds is not None else None
        )
        # Inproc stream: emit characters as deltas; honor cancel / timeout between tokens.
        payload = f"echo:{prompt}"[: max(1, max_tokens)]
        for index, ch in enumerate(payload):
            if cancel and cancel.cancelled:
                latency = timer.finish(source="inproc_stream_cancelled")
                yield {
                    "delta": "",
                    "finish_reason": "cancelled",
                    "index": index,
                    "revision_id": worker.revision_id,
                    "cancelled": True,
                    "reason": cancel.reason or "client_disconnect",
                    "latency": latency.public_dict(),
                }
                return
            if deadline is not None and time.perf_counter() >= deadline:
                if cancel is not None:
                    cancel.cancel("timeout")
                latency = timer.finish(source="inproc_stream_timeout")
                yield {
                    "delta": "",
                    "finish_reason": "timeout",
                    "index": index,
                    "revision_id": worker.revision_id,
                    "cancelled": True,
                    "reason": "timeout",
                    "latency": latency.public_dict(),
                }
                return
            if token_delay_seconds > 0:
                await asyncio.sleep(token_delay_seconds)
            else:
                await asyncio.sleep(0)  # yield event loop
            if index == 0:
                timer.mark_first_token()
            yield {
                "delta": ch,
                "finish_reason": None,
                "index": index,
                "revision_id": worker.revision_id,
            }
        latency = timer.finish(source="inproc_stream")
        yield {
            "delta": "",
            "finish_reason": "stop",
            "index": len(payload),
            "revision_id": worker.revision_id,
            "usage": {"completion_tokens": len(payload)},
            "latency": latency.public_dict(),
        }

    def reconcile_workers(self) -> list[dict[str, Any]]:
        changed = self.supervisor.reconcile()
        # Drop mappings for dead workers
        dead_ids = {w.worker_id for w in changed if w.state == WorkerState.DEAD}
        self._model_to_worker = {
            mid: wid for mid, wid in self._model_to_worker.items() if wid not in dead_ids
        }
        return [w.public_dict() for w in changed]
