"""Shared worker claim/execute loop — no import of Data.backend.main."""

from __future__ import annotations

import os
import signal
import threading
import time
import traceback
from typing import Any, Callable

from Data.modules.jobs.states import JobState

from .admission import ResourceAdmission, ResourceClass
from .events import get_worker_event_emitter, resolve_human_title
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

    emitter = get_worker_event_emitter()
    emitter.worker_ready(pool=pool_id, worker_id=worker_id, worker_pid=os.getpid())

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
            human = resolve_human_title(
                capability_id=getattr(job, "capability_id", None),
                metadata=getattr(job, "metadata", None),
                arguments=getattr(job, "arguments", None),
                domain=getattr(job, "domain", None) or pool_id,
            )
            emitter.job_waiting_resources(
                job_id=job.job_id,
                capability_id=str(getattr(job, "capability_id", "") or ""),
                reason=str(decision.reason or "RESOURCE_UNAVAILABLE"),
                pool=pool_id,
                worker_id=worker_id,
                human_title=human,
                domain=getattr(job, "domain", None) or pool_id,
            )
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

        # Long-handler heartbeats: keep BOTH worker registry + job lease fresh.
        hb_stop = threading.Event()
        lease_lost = threading.Event()
        cancel_fence = threading.Event()
        ctx["worker_id"] = worker_id
        ctx["current_job_id"] = job.job_id
        ctx["lease_ttl_seconds"] = lease_ttl
        ctx["lease_lost"] = lease_lost
        ctx["job_cancel_fence"] = cancel_fence
        job_started_monotonic = time.monotonic()
        human_title = resolve_human_title(
            capability_id=getattr(job, "capability_id", None),
            metadata=getattr(job, "metadata", None),
            arguments=getattr(job, "arguments", None),
            domain=getattr(job, "domain", None) or pool_id,
        )
        emitter.job_started(
            job_id=job.job_id,
            capability_id=str(getattr(job, "capability_id", "") or ""),
            pool=pool_id,
            worker_id=worker_id,
            worker_pid=os.getpid(),
            human_title=human_title,
            domain=getattr(job, "domain", None) or pool_id,
            attempt=getattr(job, "attempt_number", None),
            metadata=getattr(job, "metadata", None),
            arguments=getattr(job, "arguments", None),
        )

        def _job_cancel_check() -> bool:
            if lease_lost.is_set() or cancel_fence.is_set() or stop["flag"]:
                return True
            try:
                refreshed = store.get(job.job_id)
            except Exception:  # noqa: BLE001
                return False
            if refreshed is None:
                return True
            state_name = getattr(getattr(refreshed, "state", None), "name", None) or str(
                getattr(refreshed, "state", "")
            )
            if state_name in {"CANCEL_REQUESTED", "CANCELLED"}:
                return True
            owner = getattr(refreshed, "lease_owner", None)
            if owner and owner != worker_id:
                lease_lost.set()
                cancel_fence.set()
                return True
            return False

        ctx["job_cancel_check"] = _job_cancel_check

        def _heartbeat_while_busy() -> None:
            # Renew well inside the lease TTL so brief scheduling delays cannot
            # expire a legitimately owned lease (TTL=30 → ~5s; TTL=1 → ~0.3s).
            interval = max(0.1, min(float(hb_every), float(lease_ttl) / 3.0))

            def _beat_once() -> bool:
                if hb_stop.is_set():
                    return False
                try:
                    reg = registry.heartbeat(
                        worker_id,
                        state=WorkerInstanceState.BUSY,
                        current_job_id=job.job_id,
                    )
                    if reg is None:
                        if not hb_stop.is_set():
                            lease_lost.set()
                            cancel_fence.set()
                            print(
                                f"[{pool_id}-worker] lost worker registry during job={job.job_id}",
                                flush=True,
                            )
                        return False
                except Exception:  # noqa: BLE001
                    pass
                if hb_stop.is_set():
                    return False
                try:
                    if hasattr(store, "heartbeat_lease"):
                        store.heartbeat_lease(
                            job.job_id,
                            worker_id=worker_id,
                            ttl_seconds=lease_ttl,
                        )
                except ValueError as exc:
                    if not hb_stop.is_set():
                        lease_lost.set()
                        cancel_fence.set()
                        print(
                            f"[{pool_id}-worker] job lease lost job={job.job_id}: {exc}",
                            flush=True,
                        )
                    return False
                except Exception:  # noqa: BLE001
                    pass
                return True

            # Immediate beat so long handlers never wait a full interval before renewing.
            if not _beat_once():
                return
            while not hb_stop.wait(interval):
                if not _beat_once():
                    return

        hb_thread = threading.Thread(
            target=_heartbeat_while_busy,
            name=f"{pool_id}-hb-{job.job_id[:8]}",
            daemon=True,
        )
        hb_thread.start()

        try:
            # Cooperative cancel observation
            refreshed = store.get(job.job_id)
            if refreshed is not None and refreshed.state.name == "CANCEL_REQUESTED":
                store.transition(
                    job.job_id,
                    JobState.CANCELLED,
                    error=getattr(refreshed, "cancel_reason", None) or "Cancelled by request",
                )
            elif lease_lost.is_set():
                try:
                    store.transition(
                        job.job_id,
                        JobState.FAILED,
                        error="lease_lost_before_handler",
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                if handler is not None:
                    result = handler(ctx, job)
                else:
                    result = _default_gateway_execute(runtime, store, job, worker_id, lease_ttl)
                if result is not None and refreshed is not None:
                    pass  # handler owns transitions
                # If lease was lost mid-flight and handler did not fail the job, fence.
                if lease_lost.is_set():
                    latest = store.get(job.job_id)
                    if latest is not None and latest.state == JobState.RUNNING:
                        try:
                            store.transition(
                                job.job_id,
                                JobState.FAILED,
                                error="lease_lost_during_handler",
                            )
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            try:
                store.transition(job.job_id, JobState.FAILED, error=err)
            except Exception:  # noqa: BLE001
                print(traceback.format_exc(), flush=True)
        finally:
            hb_stop.set()
            hb_thread.join(timeout=max(1.0, float(hb_every)))
            admission.release(decision.reservation_id)
            try:
                store.release_lease(job.job_id, worker_id=worker_id)
            except Exception:  # noqa: BLE001
                pass
            registry.heartbeat(worker_id, state=WorkerInstanceState.READY, clear_job=True)
            ctx.pop("job_cancel_check", None)
            ctx.pop("lease_lost", None)
            ctx.pop("job_cancel_fence", None)
            ctx.pop("current_job_id", None)

        duration_ms = (time.monotonic() - job_started_monotonic) * 1000.0
        final = None
        try:
            final = store.get(job.job_id)
        except Exception:  # noqa: BLE001
            final = None
        final_state = getattr(getattr(final, "state", None), "name", None) or ""
        cap_id = str(getattr(job, "capability_id", "") or "")
        domain = getattr(job, "domain", None) or pool_id
        if final_state == "COMPLETED":
            emitter.job_completed(
                job_id=job.job_id,
                capability_id=cap_id,
                duration_ms=duration_ms,
                pool=pool_id,
                worker_id=worker_id,
                human_title=human_title,
                domain=domain,
                metadata=getattr(job, "metadata", None),
                arguments=getattr(job, "arguments", None),
            )
        elif final_state == "CANCELLED":
            emitter.job_cancelled(
                job_id=job.job_id,
                capability_id=cap_id,
                pool=pool_id,
                worker_id=worker_id,
                human_title=human_title,
                domain=domain,
            )
        elif final_state in {"FAILED", "RETRY_WAIT"} or (
            final is not None and getattr(final, "error", None)
        ):
            err_code = getattr(final, "error_code", None) if final is not None else None
            err_msg = getattr(final, "error", None) if final is not None else None
            if final_state == "RETRY_WAIT":
                emitter.job_retry(
                    job_id=job.job_id,
                    capability_id=cap_id,
                    attempt=getattr(final, "attempt_number", None) if final else None,
                    pool=pool_id,
                    worker_id=worker_id,
                    human_title=human_title,
                    domain=domain,
                )
            else:
                emitter.job_failed(
                    job_id=job.job_id,
                    capability_id=cap_id,
                    error_code=err_code or err_msg,
                    message=err_msg,
                    duration_ms=duration_ms,
                    pool=pool_id,
                    worker_id=worker_id,
                    human_title=human_title,
                    domain=domain,
                    metadata=getattr(job, "metadata", None),
                    arguments=getattr(job, "arguments", None),
                )

        processed += 1
        if max_jobs is not None and processed >= max_jobs:
            break
        if once:
            break

    registry.mark_state(worker_id, WorkerInstanceState.STOPPED)
    emitter.worker_stopping(pool=pool_id, worker_id=worker_id)
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
        try:
            store.transition(
                job.job_id,
                JobState.FAILED,
                error=str(exc),
                expected_lease_owner=worker_id,
            )
        except Exception:  # noqa: BLE001 — stale lease / concurrent terminal
            pass
        return None

    if cap_result.status == CapabilityStatus.COMPLETED:
        store.transition(
            job.job_id,
            JobState.COMPLETED,
            result={"output": getattr(cap_result, "output", None) or cap_result.public_dict()},
            expected_lease_owner=worker_id,
        )
    elif cap_result.status == CapabilityStatus.REJECTED:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=str(getattr(cap_result, "error", "rejected")),
            expected_lease_owner=worker_id,
        )
    else:
        store.transition(
            job.job_id,
            JobState.FAILED,
            error=str(getattr(cap_result, "error", None) or cap_result.status),
            expected_lease_owner=worker_id,
        )
    return {"status": cap_result.status.value if hasattr(cap_result.status, "value") else str(cap_result.status)}
