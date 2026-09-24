"""Shared worker claim/execute loop — no import of Data.backend.main."""

from __future__ import annotations

import os
import signal
import time
import traceback
from typing import Any, Callable

from Data.modules.jobs.states import JobState

from .admission import ResourceAdmission, ResourceClass
from .pools import POOL_CATALOG
from .protocol import WorkerInstanceState
from .registry import WorkerRegistry, utc_now
from .settings import load_worker_settings


HandlerFn = Callable[[Any, Any], dict[str, Any] | None]


def build_minimal_job_context() -> dict[str, Any]:
    """Process-safe factories — never imports backend.main."""
    from Data.backend.config import load_settings
    from Data.modules.execution import ExecutionGateway, build_default_catalog
    from Data.modules.jobs.resources import ResourceManager
    from Data.modules.jobs.runtime import JobRuntime
    from Data.modules.jobs.store import JobStore

    settings = load_settings()
    job_store = JobStore(settings.database_path)
    job_store.initialize()
    gateway = ExecutionGateway(catalog=build_default_catalog())
    resources = ResourceManager(settings.resources.max_job_concurrency)
    job_runtime = JobRuntime(job_store, gateway, resources)
    registry = WorkerRegistry(settings.database_path)
    registry.initialize()
    admission = ResourceAdmission(settings.database_path)
    admission.initialize()
    worker_settings = load_worker_settings()
    return {
        "settings": settings,
        "job_store": job_store,
        "job_runtime": job_runtime,
        "gateway": gateway,
        "registry": registry,
        "admission": admission,
        "worker_settings": worker_settings,
    }


def run_pool_loop(
    *,
    pool_id: str,
    handler: HandlerFn | None = None,
    once: bool = False,
    max_jobs: int | None = None,
) -> int:
    """Register, heartbeat, claim, execute, release — until stop."""
    if pool_id not in POOL_CATALOG:
        raise ValueError(f"Unknown pool: {pool_id}")

    ctx = build_minimal_job_context()
    store = ctx["job_store"]
    runtime = ctx["job_runtime"]
    registry = ctx["registry"]
    admission = ctx["admission"]
    wsettings = ctx["worker_settings"]
    defn = POOL_CATALOG[pool_id]

    worker_id = os.environ.get("LEVIATHAN_WORKER_ID") or f"{pool_id}-{os.getpid()}"
    slot = int(os.environ.get("LEVIATHAN_WORKER_SLOT") or "0")
    generation = os.environ.get("LEVIATHAN_WORKER_SUPERVISOR_GENERATION")
    from .process import process_start_identity_for
    from .protocol import WorkerRegistration, WORKER_PROTOCOL_VERSION

    identity = process_start_identity_for(os.getpid())
    stop = {"flag": False}

    def _stop(*_a: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    registry.upsert(
        WorkerRegistration(
            worker_id=worker_id,
            pool_id=pool_id,
            slot=slot,
            pid=os.getpid(),
            process_start_identity=identity,
            protocol_version=WORKER_PROTOCOL_VERSION,
            supported_job_kinds=defn.job_kinds,
            started_at=utc_now(),
            last_heartbeat_at=utc_now(),
            state=WorkerInstanceState.READY,
            supervisor_generation=generation,
        )
    )

    processed = 0
    poll = float(wsettings.poll_seconds)
    lease_ttl = float(wsettings.lease_ttl_seconds)
    hb_every = float(wsettings.heartbeat_seconds)
    last_hb = 0.0
    draining = False

    print(f"[{pool_id}-worker] ready worker_id={worker_id} pid={os.getpid()}", flush=True)

    while not stop["flag"]:
        now = time.time()
        if now - last_hb >= hb_every:
            # Self-fence if supervisor generation lease is gone too long — checked via registry row.
            reg = registry.heartbeat(
                worker_id,
                state=WorkerInstanceState.DRAINING if draining else WorkerInstanceState.READY,
            )
            last_hb = now
            if reg is None:
                print(f"[{pool_id}-worker] lost registry — exiting", flush=True)
                break

        if draining:
            time.sleep(poll)
            continue

        # Capability filter for this pool
        capability_ids = None
        if defn.job_kinds:
            # Exact kinds only when no trailing dot; prefix kinds claimed via worker_pool column when present.
            exact = {k for k in defn.job_kinds if not k.endswith(".")}
            capability_ids = exact or None

        claim_kwargs: dict[str, Any] = {}
        if capability_ids:
            claim_kwargs["capability_ids"] = capability_ids
        # Prefer worker_pool column when store supports it
        if hasattr(store, "claim_next_for_pool"):
            job = store.claim_next_for_pool(
                pool_id=pool_id,
                worker_id=worker_id,
                lease_ttl_seconds=lease_ttl,
            )
        else:
            job = store.claim_next_queued(**claim_kwargs)
            if job is not None and hasattr(store, "acquire_lease"):
                try:
                    store.acquire_lease(job.job_id, worker_id=worker_id, ttl_seconds=lease_ttl)
                except Exception:  # noqa: BLE001
                    pass

        if job is None:
            if once:
                break
            # Idle backoff with light jitter
            time.sleep(poll + (os.getpid() % 7) * 0.01)
            continue

        registry.heartbeat(
            worker_id,
            state=WorkerInstanceState.BUSY,
            current_job_id=job.job_id,
        )

        resource_class = getattr(job, "resource_class", None) or "CPU_LIGHT"
        try:
            rc = ResourceClass(str(resource_class))
        except ValueError:
            rc = ResourceClass.CPU_LIGHT

        decision = admission.try_reserve(
            job_id=job.job_id,
            worker_id=worker_id,
            resource_class=rc,
            requested=getattr(job, "resource_request", None) or {},
            ttl_seconds=max(lease_ttl * 4, 60.0),
            latency_class=getattr(job, "latency_class", "background") or "background",
        )
        if not decision.allowed:
            # Put back to queued if possible; otherwise leave for retry path.
            try:
                if hasattr(store, "transition"):
                    from Data.modules.jobs.states import JobState as JS

                    # Soft release: mark retry wait briefly via metadata when available
                    store.release_lease(job.job_id, worker_id=worker_id)
                    if hasattr(store, "schedule_retry"):
                        store.schedule_retry(
                            job.job_id,
                            delay_seconds=poll * 4,
                            error=decision.reason,
                        )
                    else:
                        store.transition(job.job_id, JS.QUEUED, error=decision.reason)
            except Exception:  # noqa: BLE001
                pass
            registry.heartbeat(worker_id, state=WorkerInstanceState.READY, clear_job=True)
            time.sleep(poll)
            continue

        try:
            # Cooperative cancel observation
            refreshed = store.get(job.job_id)
            if refreshed is not None and refreshed.state.name == "CANCEL_REQUESTED":
                store.transition(
                    job.job_id,
                    JobState.CANCELLED,
                    error=getattr(refreshed, "cancel_reason", None) or "Cancelled by request",
                )
            else:
                if handler is not None:
                    result = handler(ctx, job)
                else:
                    result = _default_gateway_execute(runtime, store, job, worker_id, lease_ttl)
                if result is not None and refreshed is not None:
                    pass  # handler owns transitions
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            try:
                store.transition(job.job_id, JobState.FAILED, error=err)
            except Exception:  # noqa: BLE001
                print(traceback.format_exc(), flush=True)
        finally:
            admission.release(decision.reservation_id)
            try:
                store.release_lease(job.job_id, worker_id=worker_id)
            except Exception:  # noqa: BLE001
                pass
            registry.heartbeat(worker_id, state=WorkerInstanceState.READY, clear_job=True)

        processed += 1
        print(f"[{pool_id}-worker] finished job={job.job_id}", flush=True)
        if max_jobs is not None and processed >= max_jobs:
            break
        if once:
            break

    registry.mark_state(worker_id, WorkerInstanceState.STOPPED)
    return processed


def _default_gateway_execute(
    runtime: Any,
    store: Any,
    job: Any,
    worker_id: str,
    lease_ttl: float,
) -> dict[str, Any] | None:
    """Execute via JobRuntime gateway path for general capabilities."""
    from Data.modules.execution import CapabilityRequest, CapabilityStatus

    # Heartbeat mid-flight
    try:
        store.heartbeat_lease(job.job_id, worker_id=worker_id, ttl_seconds=lease_ttl)
    except Exception:  # noqa: BLE001
        pass

    cancel_states = {"CANCEL_REQUESTED", "CANCELLED"}
    refreshed = store.get(job.job_id)
    if refreshed is not None and refreshed.state.value in cancel_states:
        if refreshed.state != JobState.CANCELLED:
            store.transition(job.job_id, JobState.CANCELLED, error="Cancelled by request")
        return None

    try:
        cap_result = runtime.gateway.execute(
            CapabilityRequest(
                capability_id=job.capability_id,
                arguments=dict(job.arguments or {}),
                run_id=job.run_id,
                approval_id=job.approval_id,
                requested_by=job.requested_by,
            )
        )
    except Exception as exc:  # noqa: BLE001
        store.transition(job.job_id, JobState.FAILED, error=str(exc))
        return None

    if cap_result.status == CapabilityStatus.COMPLETED:
        store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"output": getattr(cap_result, "output", None) or cap_result.public_dict()},
        )
    elif cap_result.status == CapabilityStatus.REJECTED:
        store.transition(job.job_id, JobState.FAILED, error=str(getattr(cap_result, "error", "rejected")))
    else:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=str(getattr(cap_result, "error", None) or cap_result.status),
        )
    return {"status": cap_result.status.value if hasattr(cap_result.status, "value") else str(cap_result.status)}
