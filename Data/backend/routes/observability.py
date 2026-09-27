"""Observability / Console / Performance HTTP surfaces."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from Data.modules.metrics import MetricsCollector, TimeSeriesStore
from Data.modules.observability import (
    ObservabilityHub,
    OperatorCommandRegistry,
    SystemTelemetrySampler,
)


class OperatorCommandBody(BaseModel):
    command: str = Field(min_length=1, max_length=2_000)


# Cache for jobs_completed_24h — 2s polling must not hammer SQLite.
_JOBS_24H_LOCK = threading.Lock()
_JOBS_24H_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0, "path": None}
_JOBS_24H_TTL_S = 30.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _count_jobs_completed_24h(job_store: Any | None) -> int | None:
    """Bounded COUNT via JobStore; cached ~30s. None when store unavailable."""
    if job_store is None or not hasattr(job_store, "count_completed_since"):
        return None
    path = str(getattr(job_store, "path", "") or "")
    now = time.time()
    with _JOBS_24H_LOCK:
        if (
            _JOBS_24H_CACHE["path"] == path
            and now < float(_JOBS_24H_CACHE["expires_at"])
            and _JOBS_24H_CACHE["value"] is not None
        ):
            return int(_JOBS_24H_CACHE["value"])
    since = (_utc_now() - timedelta(hours=24)).isoformat(timespec="seconds")
    try:
        count = int(job_store.count_completed_since(since))
    except Exception:  # noqa: BLE001 — leave unmeasured rather than invent
        return None
    with _JOBS_24H_LOCK:
        _JOBS_24H_CACHE["value"] = count
        _JOBS_24H_CACHE["expires_at"] = now + _JOBS_24H_TTL_S
        _JOBS_24H_CACHE["path"] = path
    return count


def _tasks_per_min(
    *,
    job_runtime: Any | None,
    timeseries: TimeSeriesStore,
) -> float | None:
    """Rolling tasks/min from jobs.completed timeseries or JobRuntime telemetry.

    Observes the cumulative completed counter into timeseries on each call.
    Requires ~60s of samples with a non-negative delta — otherwise UNMEASURED.
    """
    completed: int | None = None
    if job_runtime is not None:
        try:
            telemetry = getattr(job_runtime, "telemetry", None) or {}
            if "completed" in telemetry:
                completed = int(telemetry["completed"])
        except (TypeError, ValueError):
            completed = None

    now_ms = time.time() * 1000
    if completed is not None:
        timeseries.observe("jobs.completed", float(completed))

    # Prefer explicit jobs.completed series over ~60s window.
    try:
        points = timeseries.range("jobs.completed", since_ms=now_ms - 90_000, limit=500)
    except Exception:  # noqa: BLE001
        points = []
    if len(points) < 2:
        return None
    first = points[0]
    last = points[-1]
    try:
        dt_s = (float(last["ts_ms"]) - float(first["ts_ms"])) / 1000.0
        dv = float(last["value"]) - float(first["value"])
    except (KeyError, TypeError, ValueError):
        return None
    # Need a meaningful window (~60s). Counter reset → negative dv → unmeasured.
    if dt_s < 45.0 or dv < 0:
        return None
    return (dv / dt_s) * 60.0


def _operator_metrics(
    *,
    job_runtime: Any | None,
    job_store: Any | None,
    metrics: MetricsCollector,
    timeseries: TimeSeriesStore,
) -> dict[str, Any]:
    tasks_per_min = _tasks_per_min(job_runtime=job_runtime, timeseries=timeseries)
    jobs_24h = _count_jobs_completed_24h(job_store)

    # native_ops_per_sec / docs_per_sec only when already instrumented — never invent.
    snap = metrics.snapshot().public_dict()
    gauges = dict(snap.get("gauges") or {})
    counters = dict(snap.get("counters") or {})
    native = None
    docs = None
    for key in ("native_ops_per_sec", "embeddings_per_sec"):
        if key in gauges and isinstance(gauges[key], (int, float)):
            native = float(gauges[key])
            break
        if key in counters and isinstance(counters[key], (int, float)):
            native = float(counters[key])
            break
    for key in ("docs_per_sec", "documents_per_sec"):
        if key in gauges and isinstance(gauges[key], (int, float)):
            docs = float(gauges[key])
            break
        if key in counters and isinstance(counters[key], (int, float)):
            docs = float(counters[key])
            break

    return {
        "tasks_per_min": tasks_per_min,
        "jobs_completed_24h": jobs_24h,
        "native_ops_per_sec": native,
        "docs_per_sec": docs,
        "truth": {
            "unmeasured_is_null": True,
            "tasks_per_min_requires_rolling_window": True,
            "jobs_completed_24h_cached_s": _JOBS_24H_TTL_S,
            "no_fabricated_zeros": True,
        },
    }


def build_observability_router(
    *,
    observability: ObservabilityHub,
    operator: OperatorCommandRegistry,
    metrics: MetricsCollector,
    timeseries: TimeSeriesStore,
    sampler: SystemTelemetrySampler,
    component_health_fn: Any | None = None,
    database_path: Any | None = None,
    database_paths: Any | None = None,
    job_runtime: Any | None = None,
    job_store: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["observability"])

    @router.get("/api/events")
    def list_events(
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        before: Annotated[int | None, Query(ge=0)] = None,
        after: Annotated[int | None, Query(ge=0)] = None,
        level: Annotated[str | None, Query()] = None,
        category: Annotated[str | None, Query()] = None,
        subsystem: Annotated[str | None, Query()] = None,
        source: Annotated[str | None, Query()] = None,
        correlation_id: Annotated[str | None, Query()] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        since_ms: Annotated[float | None, Query()] = None,
        until_ms: Annotated[float | None, Query()] = None,
    ) -> dict:
        events = observability.query_history(
            limit=limit,
            before_sequence=before,
            after_sequence=after,
            level=level,
            category=category,
            subsystem=subsystem,
            source=source,
            correlation_id=correlation_id,
            q=q,
            since_ms=since_ms,
            until_ms=until_ms,
            newest_first=True,
        )
        return {
            "events": events,
            "latest_sequence": observability.latest_sequence(),
            "snapshot": observability.snapshot(),
            "truth": {
                "durable": observability.store is not None,
                "redacted": True,
                "backend_authoritative": True,
            },
        }

    @router.get("/api/events/stream")
    async def stream_events(
        request: Request,
        last_event_id: Annotated[str | None, Query()] = None,
    ) -> StreamingResponse:
        # Prefer Last-Event-ID header; fall back to query for fetch-stream clients.
        header_id = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
        cursor_raw = header_id or last_event_id or "0"
        try:
            cursor = max(0, int(cursor_raw))
        except ValueError:
            cursor = 0

        async def gen():
            # Backfill missed events after reconnect
            backfill = observability.events_after(cursor, limit=500)
            for item in backfill:
                seq = item.get("sequence")
                payload = __import__("json").dumps(item, default=str, separators=(",", ":"))
                if seq is not None:
                    yield f"id: {seq}\nevent: event\ndata: {payload}\n\n"
                else:
                    yield f"event: event\ndata: {payload}\n\n"
            async for chunk in observability.broker.stream(heartbeat_seconds=15.0):
                if await request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/console/commands")
    def list_operator_commands() -> dict:
        return {"commands": operator.list_commands()}

    @router.post("/api/console/command")
    def run_operator_command(body: OperatorCommandBody) -> dict:
        started = time.time()
        result = operator.execute(body.command)
        duration_ms = (time.time() - started) * 1000
        observability.emit(
            "console",
            "command",
            level="success" if result.ok else "error",
            message=f"operator command {'ok' if result.ok else 'failed'}: {body.command[:120]}",
            payload={
                "command": body.command[:500],
                "ok": result.ok,
                "error": result.error,
            },
            duration_ms=duration_ms,
            success=result.ok,
            actor="operator",
            source="console",
        )
        timeseries.observe_latency_ms("console.command", duration_ms)
        if not result.ok:
            # Still 200 with ok=false for expected validation failures; unknown shell attempts too.
            return {"result": result.public_dict()}
        return {"result": result.public_dict()}

    @router.get("/api/performance/snapshot")
    def performance_snapshot() -> dict:
        system = sampler.latest_public()
        metrics_snap = metrics.snapshot().public_dict()
        operator_block = _operator_metrics(
            job_runtime=job_runtime,
            job_store=job_store,
            metrics=metrics,
            timeseries=timeseries,
        )
        # Surface operator rates on gauges so existing launcher clients find them.
        gauges = dict(metrics_snap.get("gauges") or {})
        for key in (
            "tasks_per_min",
            "jobs_completed_24h",
            "native_ops_per_sec",
            "docs_per_sec",
        ):
            val = operator_block.get(key)
            if val is not None:
                gauges[key] = float(val)
        metrics_snap = {**metrics_snap, "gauges": gauges}
        latency = {
            "http": timeseries.percentiles("http.request"),
            "capability": timeseries.percentiles("capability.execute"),
            "mcp": timeseries.percentiles("mcp.call"),
            "workflow": timeseries.percentiles("workflow.run"),
        }
        health = component_health_fn() if callable(component_health_fn) else []
        inference_efficiency = None
        try:
            from Data.modules.context.efficiency import get_efficiency_plane

            inference_efficiency = get_efficiency_plane().snapshot()
        except Exception:  # noqa: BLE001
            inference_efficiency = {
                "metrics": None,
                "truth": {"unmeasured": True, "unavailable": True},
            }
        try:
            from Data.modules.common.db_contention import (
                db_contention_snapshot,
                three_database_contention_snapshot,
            )

            db_contention = db_contention_snapshot(database_path)
            db_contention_by_domain = three_database_contention_snapshot(database_paths)
        except Exception:  # noqa: BLE001
            db_contention = {
                "dbFileSize": "UNMEASURED",
                "walSize": "UNMEASURED",
                "busyRetries": "UNMEASURED",
                "commitQueueDepth": "UNMEASURED",
                "truth": {"unmeasured": True},
            }
            db_contention_by_domain = {
                "domains": {
                    "CONTROL": {"status": "UNMEASURED"},
                    "KNOWLEDGE": {"status": "UNMEASURED"},
                    "MARKET": {"status": "UNMEASURED"},
                },
                "truth": {"unmeasured": True, "perDomain": True},
            }
        try:
            from Data.modules.workers.native_compute import probe_capabilities
            caps = probe_capabilities()
            native_data_plane = {
                "status": caps.status.value if hasattr(caps.status, "value") else str(caps.status),
                "protocolVersion": caps.protocol_version,
                "operations": list(caps.operations or [])[:32],
                "binaryPath": caps.binary_path,
                "detail": (caps.detail or "")[:300],
                "truth": {"workerFabricAccelerator": True, "notSecondControlPlane": True},
            }
        except Exception:  # noqa: BLE001
            native_data_plane = {
                "status": "UNMEASURED",
                "protocolVersion": None,
                "operations": [],
                "binaryPath": None,
                "detail": "probe_failed",
                "truth": {"unmeasured": True},
            }
        return {
            "system": system,
            "metrics": metrics_snap,
            "operator": operator_block,
            "latency": latency,
            "hot_paths": timeseries.hot_paths(limit=25),
            "timeseries": timeseries.snapshot(),
            "components": health,
            "observability": observability.snapshot(),
            "inferenceEfficiency": inference_efficiency,
            "dbContention": db_contention,
            "dbContentionByDomain": db_contention_by_domain,
            "nativeDataPlane": native_data_plane,
            "product_truth": {
                "vocabulary": [
                    "operational",
                    "degraded",
                    "experimental",
                    "fixture",
                    "unavailable",
                    "unconfigured",
                    "unmeasured",
                ],
            },
            "truth": {
                "measured": True,
                "unavailable_is_null": True,
                "no_fabricated_history": True,
                "import_success_is_not_operational": True,
                "status_derives_from_evidence": True,
                "inference_efficiency_is_real_or_unmeasured": True,
            },
        }

    @router.get("/api/performance/series")
    def performance_series(
        name: Annotated[str, Query(min_length=1, max_length=120)],
        since_ms: Annotated[float | None, Query()] = None,
        until_ms: Annotated[float | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 600,
    ) -> dict:
        points = timeseries.range(name, since_ms=since_ms, until_ms=until_ms, limit=limit)
        return {
            "name": name,
            "points": points,
            "truth": {"missing_sample_is_not_zero": True},
        }

    return router
