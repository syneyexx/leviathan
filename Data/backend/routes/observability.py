"""Observability / Console / Performance HTTP surfaces."""

from __future__ import annotations

import time
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


def build_observability_router(
    *,
    observability: ObservabilityHub,
    operator: OperatorCommandRegistry,
    metrics: MetricsCollector,
    timeseries: TimeSeriesStore,
    sampler: SystemTelemetrySampler,
    component_health_fn: Any | None = None,
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
        latency = {
            "http": timeseries.percentiles("http.request"),
            "capability": timeseries.percentiles("capability.execute"),
            "mcp": timeseries.percentiles("mcp.call"),
            "workflow": timeseries.percentiles("workflow.run"),
        }
        health = component_health_fn() if callable(component_health_fn) else []
        return {
            "system": system,
            "metrics": metrics_snap,
            "latency": latency,
            "hot_paths": timeseries.hot_paths(limit=25),
            "timeseries": timeseries.snapshot(),
            "components": health,
            "observability": observability.snapshot(),
            "truth": {
                "measured": True,
                "unavailable_is_null": True,
                "no_fabricated_history": True,
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
