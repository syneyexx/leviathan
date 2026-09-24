"""Model residency manager — leases, single-flight load, idle unload.

Coordinates RuntimeManager / ServingSupervisor / ResourceManager.
Does NOT replace the Model Control Plane.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from Data.modules.models.contracts import (
    LoadOptions,
    ModelLifecycleState,
    ModelResidencySnapshot,
    PhysicalPlacement,
    ResidencyLease,
    ResidencyPolicy,
    ResidencyPolicyKind,
    ResidencyState,
    ResourceEstimate,
    ResourceProvenance,
)
from Data.modules.models.errors import (
    MODEL_ACTIVE_LEASES,
    MODEL_RESIDENCY_UNAVAILABLE,
    MODEL_RUNTIME_UNAVAILABLE,
    MODEL_START_TIMEOUT,
    MODEL_WORKER_DIED,
    UNSUPPORTED_RESIDENCY_POLICY,
    ModelControlError,
)


def _map_lifecycle(state: ResidencyState) -> ModelLifecycleState:
    mapping = {
        ResidencyState.UNLOADED: ModelLifecycleState.AVAILABLE,
        ResidencyState.STARTING: ModelLifecycleState.LOADING,
        ResidencyState.LOADING: ModelLifecycleState.LOADING,
        ResidencyState.READY: ModelLifecycleState.LOADED,
        ResidencyState.ACTIVE: ModelLifecycleState.LOADED,
        ResidencyState.IDLE: ModelLifecycleState.LOADED,
        ResidencyState.DRAINING: ModelLifecycleState.UNLOADING,
        ResidencyState.STOPPING: ModelLifecycleState.UNLOADING,
        ResidencyState.ERROR: ModelLifecycleState.ERROR,
        ResidencyState.EXTERNAL: ModelLifecycleState.AVAILABLE,
        ResidencyState.UNAVAILABLE: ModelLifecycleState.OFFLINE,
    }
    return mapping.get(state, ModelLifecycleState.UNKNOWN)


@dataclass
class _ModelResidencySlot:
    model_id: str
    state: ResidencyState = ResidencyState.UNLOADED
    placement: PhysicalPlacement = PhysicalPlacement.UNKNOWN
    managed: bool = False
    worker_id: str | None = None
    pid: int | None = None
    endpoint: str | None = None
    runtime_kind: str | None = None
    leases: dict[str, ResidencyLease] = field(default_factory=dict)
    load_started_at: float | None = None
    ready_at: float | None = None
    last_used_at: float | None = None
    idle_since: float | None = None
    next_action_at: float | None = None
    last_error: str | None = None
    load_future: asyncio.Future[Any] | None = None
    unload_handle: asyncio.TimerHandle | None = None
    last_load_result: dict[str, Any] | None = None


class ModelResidencyManager:
    """Owns live residency truth for managed and external models."""

    def __init__(
        self,
        *,
        runtime_manager: Any,
        resource_manager: Any,
        store: Any,
        registry: Any,
        serving: Any | None = None,
        observability: Any | None = None,
        default_policy: ResidencyPolicyKind = ResidencyPolicyKind.IDLE_UNLOAD,
        default_idle_unload_seconds: float = 300.0,
        allow_warm_then_unload: bool = False,
        max_managed_resident: int = 4,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.runtime = runtime_manager
        self.resources = resource_manager
        self.store = store
        self.registry = registry
        self.serving = serving
        self.observability = observability
        self.default_policy = default_policy
        self.default_idle_unload_seconds = float(default_idle_unload_seconds)
        self.allow_warm_then_unload = bool(allow_warm_then_unload)
        self.max_managed_resident = int(max_managed_resident)
        self._clock = clock or time.monotonic
        self._slots: dict[str, _ModelResidencySlot] = {}
        self._lock = asyncio.Lock()
        self._thread_lock = threading.RLock()
        self._stopped = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.observability:
            self.observability.emit("models", name, payload=payload)

    def _get_or_create_slot(self, model_id: str) -> _ModelResidencySlot:
        slot = self._slots.get(model_id)
        if slot is None:
            slot = _ModelResidencySlot(model_id=model_id)
            self._slots[model_id] = slot
        return slot

    def get_policy(self, model_id: str) -> ResidencyPolicy:
        row = None
        if hasattr(self.store, "get_residency_policy"):
            row = self.store.get_residency_policy(model_id)
        if row:
            return self._policy_from_row(row)
        return ResidencyPolicy(
            model_id=model_id,
            policy=self.default_policy,
            idle_unload_seconds=self.default_idle_unload_seconds,
            pinned=False,
        )

    def set_policy(self, model_id: str, payload: dict[str, Any]) -> ResidencyPolicy:
        current = self.get_policy(model_id)
        kind_raw = payload.get("policy", current.policy.value)
        try:
            kind = ResidencyPolicyKind(str(kind_raw))
        except ValueError as exc:
            raise ModelControlError(
                code=UNSUPPORTED_RESIDENCY_POLICY,
                message=f"Unknown residency policy: {kind_raw}",
                model_id=model_id,
                http_status=422,
            ) from exc
        if kind == ResidencyPolicyKind.WARM_THEN_UNLOAD and not self.allow_warm_then_unload:
            raise ModelControlError(
                code=UNSUPPORTED_RESIDENCY_POLICY,
                message=(
                    "WARM_THEN_UNLOAD is not supported for current runtimes — "
                    "backend cannot demote GPU→RAM warm without full unload"
                ),
                model_id=model_id,
                http_status=409,
                details={"supported": ["KEEP_HOT", "IDLE_UNLOAD"]},
            )
        load_opts = current.load_options
        raw_opts = payload.get("loadOptions", payload.get("load_options"))
        if isinstance(raw_opts, dict):
            load_opts = LoadOptions(
                context_length=raw_opts.get("contextLength", raw_opts.get("context_length")),
                gpu_offload_layers=raw_opts.get("gpuOffloadLayers", raw_opts.get("gpu_offload_layers")),
                gpu_memory_limit_bytes=raw_opts.get(
                    "gpuMemoryLimitBytes", raw_opts.get("gpu_memory_limit_bytes")
                ),
                cpu_threads=raw_opts.get("cpuThreads", raw_opts.get("cpu_threads")),
                batch_size=raw_opts.get("batchSize", raw_opts.get("batch_size")),
                flash_attention=raw_opts.get("flashAttention", raw_opts.get("flash_attention")),
                prefix_cache=raw_opts.get("prefixCache", raw_opts.get("prefix_cache")),
                continuous_batching=raw_opts.get(
                    "continuousBatching", raw_opts.get("continuous_batching")
                ),
                kv_cache_dtype=raw_opts.get("kvCacheDtype", raw_opts.get("kv_cache_dtype")),
                speculative_decoding=raw_opts.get(
                    "speculativeDecoding", raw_opts.get("speculative_decoding")
                ),
                draft_model_id=raw_opts.get("draftModelId", raw_opts.get("draft_model_id")),
                speculative_tokens=raw_opts.get(
                    "speculativeTokens", raw_opts.get("speculative_tokens")
                ),
            )
        policy = ResidencyPolicy(
            model_id=model_id,
            policy=kind,
            idle_unload_seconds=float(
                payload.get("idleUnloadSeconds", payload.get("idle_unload_seconds", current.idle_unload_seconds))
            ),
            full_unload_seconds=payload.get(
                "fullUnloadSeconds", payload.get("full_unload_seconds", current.full_unload_seconds)
            ),
            pinned=bool(payload.get("pinned", current.pinned)),
            load_options=load_opts,
        )
        if hasattr(self.store, "upsert_residency_policy"):
            self.store.upsert_residency_policy(self._policy_to_row(policy))
        return policy

    def _policy_from_row(self, row: dict[str, Any]) -> ResidencyPolicy:
        opts = row.get("load_options") or {}
        load_opts = None
        if isinstance(opts, dict) and opts:
            load_opts = LoadOptions(
                context_length=opts.get("contextLength"),
                gpu_offload_layers=opts.get("gpuOffloadLayers"),
                gpu_memory_limit_bytes=opts.get("gpuMemoryLimitBytes"),
                cpu_threads=opts.get("cpuThreads"),
                batch_size=opts.get("batchSize"),
                flash_attention=opts.get("flashAttention"),
                prefix_cache=opts.get("prefixCache"),
                continuous_batching=opts.get("continuousBatching"),
                kv_cache_dtype=opts.get("kvCacheDtype"),
                speculative_decoding=opts.get("speculativeDecoding"),
                draft_model_id=opts.get("draftModelId"),
                speculative_tokens=opts.get("speculativeTokens"),
            )
        try:
            kind = ResidencyPolicyKind(str(row.get("policy") or "IDLE_UNLOAD"))
        except ValueError:
            kind = ResidencyPolicyKind.IDLE_UNLOAD
        return ResidencyPolicy(
            model_id=row["model_id"],
            policy=kind,
            idle_unload_seconds=float(row.get("idle_unload_seconds") or self.default_idle_unload_seconds),
            full_unload_seconds=row.get("full_unload_seconds"),
            pinned=bool(row.get("pinned")),
            load_options=load_opts,
            updated_at=row.get("updated_at"),
        )

    def _policy_to_row(self, policy: ResidencyPolicy) -> dict[str, Any]:
        opts = {}
        if policy.load_options is not None:
            opts = {
                "contextLength": policy.load_options.context_length,
                "gpuOffloadLayers": policy.load_options.gpu_offload_layers,
                "gpuMemoryLimitBytes": policy.load_options.gpu_memory_limit_bytes,
                "cpuThreads": policy.load_options.cpu_threads,
                "batchSize": policy.load_options.batch_size,
                "flashAttention": policy.load_options.flash_attention,
                "prefixCache": policy.load_options.prefix_cache,
                "continuousBatching": policy.load_options.continuous_batching,
                "kvCacheDtype": policy.load_options.kv_cache_dtype,
                "speculativeDecoding": policy.load_options.speculative_decoding,
                "draftModelId": policy.load_options.draft_model_id,
                "speculativeTokens": policy.load_options.speculative_tokens,
            }
        return {
            "model_id": policy.model_id,
            "policy": policy.policy.value,
            "idle_unload_seconds": policy.idle_unload_seconds,
            "full_unload_seconds": policy.full_unload_seconds,
            "pinned": policy.pinned,
            "load_options": opts,
        }

    def snapshot(self, model_id: str) -> ModelResidencySnapshot:
        with self._thread_lock:
            slot = self._slots.get(model_id) or _ModelResidencySlot(model_id=model_id)
            policy = self.get_policy(model_id)
            estimate = None
            try:
                model = self.registry.get(model_id)
                if hasattr(self.resources, "estimate"):
                    estimate = self.resources.estimate(model, requested_context=(
                        policy.load_options.context_length if policy.load_options else None
                    ))
            except Exception:  # noqa: BLE001
                estimate = None
            return ModelResidencySnapshot(
                model_id=model_id,
                state=slot.state,
                placement=slot.placement,
                managed=slot.managed,
                worker_id=slot.worker_id,
                pid=slot.pid,
                endpoint=slot.endpoint,
                active_lease_count=len(slot.leases),
                consumers=tuple(sorted({lease.consumer for lease in slot.leases.values()})),
                policy=policy,
                last_used_at=slot.last_used_at,
                idle_since=slot.idle_since,
                next_action_at=slot.next_action_at,
                runtime_kind=slot.runtime_kind,
                load_started_at=slot.load_started_at,
                ready_at=slot.ready_at,
                last_error=slot.last_error,
                resource_estimate=estimate if isinstance(estimate, ResourceEstimate) else None,
            )

    def list_snapshots(self) -> list[ModelResidencySnapshot]:
        with self._thread_lock:
            ids = set(self._slots.keys())
        # Also include models with persisted policies
        if hasattr(self.store, "list_residency_policies"):
            for row in self.store.list_residency_policies():
                ids.add(row["model_id"])
        return [self.snapshot(mid) for mid in sorted(ids)]

    def clear_live_leases_on_startup(self) -> None:
        """Active leases are never restored — restart truth is zero leases."""
        with self._thread_lock:
            for slot in self._slots.values():
                slot.leases.clear()
                if slot.state in {
                    ResidencyState.READY,
                    ResidencyState.ACTIVE,
                    ResidencyState.IDLE,
                    ResidencyState.LOADING,
                    ResidencyState.STARTING,
                }:
                    # Without a live process we will reconcile separately.
                    pass
            self._slots.clear()
        self._emit("model.residency.startup_cleared", {"activeLeases": 0})

    async def acquire_lease(
        self,
        model_id: str,
        *,
        consumer: str,
        domain: str | None = None,
        model_role: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        job_class: str = "INTERACTIVE",
        explicit_selection: bool = False,
        managed: bool = False,
        runtime_kind: str | None = None,
        ensure_ready: bool = True,
        load_options: LoadOptions | None = None,
        external: bool = False,
        endpoint: str | None = None,
    ) -> ResidencyLease:
        if self._stopped:
            raise ModelControlError(
                code=MODEL_RESIDENCY_UNAVAILABLE,
                message="Residency manager is shutting down",
                model_id=model_id,
                http_status=503,
                retryable=True,
            )
        self._loop = asyncio.get_running_loop()
        now = self._clock()
        async with self._lock:
            slot = self._get_or_create_slot(model_id)
            slot.managed = managed
            if runtime_kind:
                slot.runtime_kind = runtime_kind
            if endpoint:
                slot.endpoint = endpoint
            self._cancel_idle_timer(slot)

            if external:
                slot.state = ResidencyState.EXTERNAL
                slot.placement = PhysicalPlacement.EXTERNAL
                slot.managed = False
                slot.pid = None
                slot.worker_id = None
            elif ensure_ready and managed:
                await self._ensure_ready_locked(slot, load_options=load_options)
            elif ensure_ready and not managed:
                # External/unmanaged — mark EXTERNAL; no worker ownership.
                if slot.state not in {ResidencyState.READY, ResidencyState.ACTIVE, ResidencyState.IDLE}:
                    slot.state = ResidencyState.EXTERNAL
                    slot.placement = PhysicalPlacement.EXTERNAL

            # Re-check after ensure (single-flight waiters re-enter with READY).
            lease = ResidencyLease(
                lease_id=str(uuid.uuid4()),
                model_id=model_id,
                consumer=consumer,
                domain=domain,
                model_role=model_role,
                run_id=run_id,
                trace_id=trace_id,
                job_class=job_class,
                explicit_selection=explicit_selection,
                acquired_at=now,
                last_activity_at=now,
            )
            slot.leases[lease.lease_id] = lease
            slot.last_used_at = now
            slot.idle_since = None
            slot.next_action_at = None
            if slot.state in {ResidencyState.READY, ResidencyState.IDLE}:
                slot.state = ResidencyState.ACTIVE
            self._emit(
                "model.residency.lease_acquired",
                {
                    "modelId": model_id,
                    "leaseId": lease.lease_id,
                    "consumer": consumer,
                    "domain": domain,
                    "modelRole": model_role,
                    "jobClass": job_class,
                    "traceId": trace_id,
                    "activeLeaseCount": len(slot.leases),
                },
            )
            return lease

    async def release_lease(self, lease_id: str, *, model_id: str | None = None) -> None:
        async with self._lock:
            slot = None
            if model_id and model_id in self._slots:
                slot = self._slots[model_id]
            else:
                for candidate in self._slots.values():
                    if lease_id in candidate.leases:
                        slot = candidate
                        break
            if slot is None:
                return
            lease = slot.leases.pop(lease_id, None)
            if lease is None:
                return
            now = self._clock()
            slot.last_used_at = now
            self._emit(
                "model.residency.lease_released",
                {
                    "modelId": slot.model_id,
                    "leaseId": lease_id,
                    "consumer": lease.consumer,
                    "activeLeaseCount": len(slot.leases),
                },
            )
            if slot.leases:
                return
            # Final lease released
            if slot.state == ResidencyState.EXTERNAL:
                return
            if not slot.managed:
                slot.state = ResidencyState.EXTERNAL
                return
            policy = self.get_policy(slot.model_id)
            if policy.policy == ResidencyPolicyKind.KEEP_HOT or policy.pinned:
                slot.state = ResidencyState.IDLE
                slot.idle_since = now
                self._emit(
                    "model.residency.idle",
                    {"modelId": slot.model_id, "policy": policy.policy.value, "keepHot": True},
                )
                return
            slot.state = ResidencyState.IDLE
            slot.idle_since = now
            delay = max(0.0, float(policy.idle_unload_seconds))
            slot.next_action_at = now + delay
            self._emit(
                "model.residency.unload_scheduled",
                {
                    "modelId": slot.model_id,
                    "delaySeconds": delay,
                    "nextActionAt": slot.next_action_at,
                },
            )
            self._schedule_idle_unload(slot, delay)

    async def touch_lease(self, lease_id: str, *, model_id: str | None = None) -> None:
        async with self._lock:
            slot = self._slots.get(model_id) if model_id else None
            if slot is None:
                for candidate in self._slots.values():
                    if lease_id in candidate.leases:
                        slot = candidate
                        break
            if slot is None:
                return
            lease = slot.leases.get(lease_id)
            if lease is None:
                return
            lease.last_activity_at = self._clock()
            slot.last_used_at = lease.last_activity_at

    async def manual_load(
        self,
        model_id: str,
        *,
        options: LoadOptions | None = None,
        managed: bool = True,
        runtime_kind: str | None = None,
        confirm_oom: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            slot = self._get_or_create_slot(model_id)
            slot.managed = managed
            if runtime_kind:
                slot.runtime_kind = runtime_kind
            if not managed:
                raise ModelControlError(
                    code=MODEL_RUNTIME_UNAVAILABLE,
                    message="Manual load is only for managed runtimes",
                    model_id=model_id,
                    http_status=409,
                )
            result = await self._ensure_ready_locked(
                slot, load_options=options, confirm_oom=confirm_oom
            )
            return {"residency": self.snapshot(model_id).public_dict(), "providerResult": result}

    async def manual_unload(self, model_id: str, *, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            slot = self._get_or_create_slot(model_id)
            if slot.leases and not force:
                raise ModelControlError(
                    code=MODEL_ACTIVE_LEASES,
                    message="Cannot unload model while active leases exist",
                    model_id=model_id,
                    http_status=409,
                    details={
                        "activeLeaseCount": len(slot.leases),
                        "consumers": sorted({lease.consumer for lease in slot.leases.values()}),
                    },
                )
            if not slot.managed:
                raise ModelControlError(
                    code=MODEL_RUNTIME_UNAVAILABLE,
                    message="External provider lifecycle is not owned by LEVIATHAN",
                    model_id=model_id,
                    http_status=409,
                    details={"hint": "Lifecycle is managed externally"},
                )
            self._cancel_idle_timer(slot)
            return await self._unload_locked(slot, reason="manual_unload")

    async def _ensure_ready_locked(
        self,
        slot: _ModelResidencySlot,
        *,
        load_options: LoadOptions | None = None,
        confirm_oom: bool = False,
    ) -> dict[str, Any]:
        """Ensure managed model is READY. Caller MUST hold ``self._lock``."""
        if slot.state in {ResidencyState.READY, ResidencyState.ACTIVE, ResidencyState.IDLE}:
            if slot.pid is not None:
                from Data.modules.common.process import pid_is_alive

                if not pid_is_alive(slot.pid):
                    slot.state = ResidencyState.ERROR
                    slot.last_error = "managed worker died"
                    self._emit("model.worker.dead", {"modelId": slot.model_id, "pid": slot.pid})
                    raise ModelControlError(
                        code=MODEL_WORKER_DIED,
                        message="Managed model worker died",
                        model_id=slot.model_id,
                        http_status=503,
                        retryable=True,
                    )
            self._emit(
                "model.residency.ready",
                {
                    "modelId": slot.model_id,
                    "residentHit": True,
                    "activeLeaseCount": len(slot.leases),
                },
            )
            return slot.last_load_result or {"alreadyLoaded": True}

        # Join in-flight single-flight load.
        if slot.load_future is not None and not slot.load_future.done():
            fut = slot.load_future
            self._lock.release()
            try:
                return await fut
            finally:
                await self._lock.acquire()

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        slot.load_future = fut
        slot.state = ResidencyState.LOADING
        slot.load_started_at = self._clock()
        slot.last_error = None
        policy = self.get_policy(slot.model_id)
        opts = load_options or policy.load_options
        self._emit(
            "model.residency.load_started",
            {"modelId": slot.model_id, "runtimeKind": slot.runtime_kind},
        )

        # Preflight + eviction while holding lock (short, deterministic).
        try:
            model = self.registry.get(slot.model_id)
            if hasattr(self.resources, "estimate"):
                estimate = self.resources.estimate(
                    model,
                    requested_context=opts.context_length if opts else None,
                )
                self._emit(
                    "model.resource.preflight",
                    {"modelId": slot.model_id, "estimate": estimate.public_dict()},
                )
                if estimate.verdict.value == "LIKELY_OOM" and not confirm_oom:
                    await self._try_evict_for_capacity_locked(exclude=slot.model_id)
                    estimate = self.resources.estimate(
                        model,
                        requested_context=opts.context_length if opts else None,
                    )
                    if estimate.verdict.value == "LIKELY_OOM" and not confirm_oom:
                        from Data.modules.models.errors import INSUFFICIENT_MEMORY

                        raise ModelControlError(
                            code=INSUFFICIENT_MEMORY,
                            message="Insufficient memory for managed model load",
                            model_id=slot.model_id,
                            http_status=409,
                            details=estimate.public_dict(),
                            retryable=False,
                        )
            resident = [
                s
                for s in self._slots.values()
                if s.managed
                and s.model_id != slot.model_id
                and s.state
                in {
                    ResidencyState.READY,
                    ResidencyState.ACTIVE,
                    ResidencyState.IDLE,
                    ResidencyState.LOADING,
                }
            ]
            if len(resident) >= self.max_managed_resident:
                await self._try_evict_for_capacity_locked(exclude=slot.model_id)
        except Exception as exc:
            slot.state = ResidencyState.ERROR
            slot.last_error = str(exc)
            slot.load_future = None
            self._emit(
                "model.residency.load_failed",
                {"modelId": slot.model_id, "error": str(exc)},
            )
            if not fut.done():
                fut.set_exception(exc)
            raise

        # Runtime load outside the lock (may take minutes).
        self._lock.release()
        load_exc: BaseException | None = None
        result: dict[str, Any] = {}
        try:
            result = await self.runtime.load(slot.model_id, opts, confirm_oom=confirm_oom)
        except BaseException as exc:  # noqa: BLE001
            load_exc = exc
        await self._lock.acquire()

        try:
            if load_exc is not None:
                slot.state = ResidencyState.ERROR
                slot.last_error = str(load_exc)
                self._emit(
                    "model.residency.load_failed",
                    {"modelId": slot.model_id, "error": str(load_exc)},
                )
                if not fut.done():
                    fut.set_exception(load_exc)
                raise load_exc

            provider_result = result.get("providerResult") or {}
            if isinstance(provider_result, dict) and isinstance(provider_result.get("worker"), dict):
                w = provider_result["worker"]
                slot.worker_id = w.get("worker_id")
                slot.pid = w.get("pid")
                slot.endpoint = w.get("endpoint") or slot.endpoint
                if w.get("state") == "UNAVAILABLE":
                    raise ModelControlError(
                        code=MODEL_RUNTIME_UNAVAILABLE,
                        message=w.get("last_error") or "managed runtime unavailable",
                        model_id=slot.model_id,
                        http_status=503,
                        details=w,
                    )
                if w.get("state") == "DEAD":
                    raise ModelControlError(
                        code=MODEL_WORKER_DIED,
                        message=w.get("last_error") or "worker died during start",
                        model_id=slot.model_id,
                        http_status=503,
                        details=w,
                    )

            from Data.modules.model_runtime.llama_cpp_command import infer_placement_from_options

            if slot.runtime_kind in {"llama_cpp", "llamacpp", "llama.cpp"}:
                slot.placement = PhysicalPlacement(infer_placement_from_options(opts))
            else:
                slot.placement = PhysicalPlacement.UNKNOWN

            slot.state = ResidencyState.READY
            slot.ready_at = self._clock()
            slot.last_load_result = result
            try:
                self.registry.set_lifecycle(
                    slot.model_id,
                    _map_lifecycle(slot.state),
                    loaded=True,
                )
            except Exception:  # noqa: BLE001
                pass
            duration_ms = (slot.ready_at - (slot.load_started_at or slot.ready_at)) * 1000.0
            self._emit(
                "model.residency.ready",
                {
                    "modelId": slot.model_id,
                    "residentHit": False,
                    "durationMs": duration_ms,
                    "workerId": slot.worker_id,
                    "pid": slot.pid,
                },
            )
            self._emit(
                "model.worker.ready",
                {"modelId": slot.model_id, "workerId": slot.worker_id, "pid": slot.pid},
            )
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as exc:
            slot.state = ResidencyState.ERROR
            slot.last_error = str(exc)
            self._emit(
                "model.residency.load_failed",
                {"modelId": slot.model_id, "error": str(exc)},
            )
            if not fut.done():
                fut.set_exception(exc)
            raise
        finally:
            slot.load_future = None

    async def _try_evict_for_capacity_locked(self, *, exclude: str) -> list[str]:
        candidates: list[_ModelResidencySlot] = []
        for slot in self._slots.values():
            if slot.model_id == exclude:
                continue
            if not slot.managed:
                continue
            if slot.leases:
                continue
            policy = self.get_policy(slot.model_id)
            if policy.pinned:
                continue
            if slot.state not in {ResidencyState.IDLE, ResidencyState.READY}:
                continue
            if slot.state in {ResidencyState.LOADING, ResidencyState.STARTING, ResidencyState.STOPPING}:
                continue
            candidates.append(slot)
        # Prefer idle, then oldest last_used
        candidates.sort(
            key=lambda s: (
                0 if s.state == ResidencyState.IDLE else 1,
                s.last_used_at if s.last_used_at is not None else 0.0,
            )
        )
        evicted: list[str] = []
        for slot in candidates:
            self._emit(
                "model.residency.eviction_started",
                {"modelId": slot.model_id, "reason": "resource_pressure"},
            )
            await self._unload_locked(slot, reason="eviction")
            self._emit(
                "model.residency.eviction_completed",
                {"modelId": slot.model_id},
            )
            evicted.append(slot.model_id)
            break  # one at a time, caller re-measures
        return evicted

    async def _unload_locked(self, slot: _ModelResidencySlot, *, reason: str) -> dict[str, Any]:
        if slot.state in {ResidencyState.UNLOADED, ResidencyState.EXTERNAL}:
            return {"unloaded": False, "reason": "already_unloaded", "residency": self.snapshot(slot.model_id).public_dict()}
        slot.state = ResidencyState.STOPPING
        self._emit(
            "model.residency.unload_started",
            {"modelId": slot.model_id, "reason": reason},
        )
        started = self._clock()
        try:
            result = await self.runtime.unload(slot.model_id)
        except ModelControlError as exc:
            slot.state = ResidencyState.ERROR
            slot.last_error = exc.message
            raise
        slot.state = ResidencyState.UNLOADED
        slot.worker_id = None
        slot.pid = None
        slot.endpoint = None
        slot.ready_at = None
        slot.idle_since = None
        slot.next_action_at = None
        slot.placement = PhysicalPlacement.UNKNOWN
        duration_ms = (self._clock() - started) * 1000.0
        self._emit(
            "model.residency.unload_completed",
            {"modelId": slot.model_id, "reason": reason, "durationMs": duration_ms},
        )
        self._emit(
            "model.worker.stopped",
            {"modelId": slot.model_id, "reason": reason},
        )
        try:
            self.registry.set_lifecycle(
                slot.model_id,
                ModelLifecycleState.AVAILABLE,
                loaded=False,
            )
        except Exception:  # noqa: BLE001
            pass
        return {"unloaded": True, "providerResult": result, "residency": self.snapshot(slot.model_id).public_dict()}

    def _cancel_idle_timer(self, slot: _ModelResidencySlot) -> None:
        if slot.unload_handle is not None:
            slot.unload_handle.cancel()
            slot.unload_handle = None
            if slot.next_action_at is not None:
                self._emit(
                    "model.residency.unload_cancelled",
                    {"modelId": slot.model_id},
                )
            slot.next_action_at = None

    def _schedule_idle_unload(self, slot: _ModelResidencySlot, delay: float) -> None:
        self._cancel_idle_timer(slot)
        loop = self._loop or asyncio.get_event_loop()

        def _fire() -> None:
            asyncio.create_task(self._idle_unload_fire(slot.model_id))

        slot.unload_handle = loop.call_later(delay, _fire)

    async def _idle_unload_fire(self, model_id: str) -> None:
        async with self._lock:
            slot = self._slots.get(model_id)
            if slot is None:
                return
            if slot.leases:
                # Race: new lease arrived — do not unload
                self._emit(
                    "model.residency.unload_cancelled",
                    {"modelId": model_id, "reason": "active_leases"},
                )
                return
            policy = self.get_policy(model_id)
            if policy.policy == ResidencyPolicyKind.KEEP_HOT or policy.pinned:
                return
            await self._unload_locked(slot, reason="idle_timeout")

    async def shutdown(self) -> None:
        self._stopped = True
        async with self._lock:
            for slot in list(self._slots.values()):
                self._cancel_idle_timer(slot)
                slot.leases.clear()
                if slot.managed and slot.state not in {
                    ResidencyState.UNLOADED,
                    ResidencyState.EXTERNAL,
                    ResidencyState.UNAVAILABLE,
                }:
                    try:
                        await self._unload_locked(slot, reason="shutdown")
                    except Exception:  # noqa: BLE001
                        pass

    def mark_worker_dead(self, model_id: str, reason: str) -> None:
        with self._thread_lock:
            slot = self._slots.get(model_id)
            if slot is None:
                return
            slot.state = ResidencyState.ERROR
            slot.last_error = reason
            slot.pid = None
            slot.worker_id = None


# Alias for exports / docs
ResidencyManager = ModelResidencyManager
