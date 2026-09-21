"""Native runtime HTTP routes — companion status, restart, metrics, benchmark."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from native_runtime import NativeRuntimeError, get_native_client

router = APIRouter(prefix="/api/native", tags=["native"])


class NativeModeBody(BaseModel):
    mode: str | None = Field(default=None, description="Optional mode override for this process only.")


@router.get("/status")
def native_status() -> dict[str, Any]:
    client = get_native_client()
    status = client.status().as_dict()
    # Refresh live health fields when connected
    if status.get("connected"):
        try:
            health = client.health()
            status["health"] = health
            status["uptime_ms"] = health.get("uptime_ms", status.get("uptime_ms"))
            status["process_count"] = health.get("active_jobs", status.get("process_count"))
            status["service_count"] = health.get("active_services", status.get("service_count"))
            status["workers"] = health.get("workers", status.get("workers"))
            status["queued_jobs"] = health.get("queued", status.get("queued_jobs"))
            status["active_jobs"] = health.get("active_jobs", status.get("active_jobs"))
            status["hades_version"] = None  # filled by diagnostics aggregator when available
            status["native_version"] = health.get("version") or status.get("version")
            status["native_protocol"] = health.get("protocol_version") or status.get("protocol_version")
            if hasattr(client, "reconcile_services_after_restart"):
                status["reconciliation"] = {
                    "generation": status.get("generation"),
                    "crash_count": status.get("crash_count"),
                    "last_crash_reason": status.get("last_crash_reason"),
                }
        except NativeRuntimeError as exc:
            status["last_error"] = exc.message
            status["connected"] = False
            status["fallback_active"] = True
    connected = bool(status.get("connected")) and not bool(status.get("fallback_active"))
    has_binary_evidence = bool(status.get("native_version") or status.get("version") or status.get("binary_path"))
    if connected and has_binary_evidence:
        status["operator_label"] = "Native Ready"
        status["accelerated"] = True
    elif status.get("last_error") or status.get("crash_count"):
        status["operator_label"] = "Native failed/crashed"
        status["accelerated"] = False
    else:
        status["operator_label"] = "Python fallback"
        status["accelerated"] = False
    return status


@router.get("/diagnostics")
def native_diagnostics() -> dict[str, Any]:
    """Engineer-facing native diagnostics for Mission Control / Settings."""
    from infrastructure.native.observability import get_native_observability

    client = get_native_client()
    status = client.status().as_dict()
    body: dict[str, Any] = {
        "native": status,
        "versions": {
            "native_version": status.get("version"),
            "native_protocol": status.get("protocol_version"),
        },
        "observability": get_native_observability().snapshot(),
    }
    if status.get("connected"):
        try:
            body["health"] = client.health()
            body["capabilities"] = client.capabilities()
            body["metrics"] = client.system_metrics()
        except NativeRuntimeError as exc:
            body["error"] = exc.as_dict()
    return body


@router.post("/restart")
def native_restart() -> dict[str, Any]:
    client = get_native_client()
    try:
        return client.restart().as_dict()
    except NativeRuntimeError as exc:
        raise HTTPException(status_code=503, detail=exc.as_dict()) from exc


@router.get("/metrics")
def native_metrics() -> dict[str, Any]:
    from infrastructure.native.python_live_metrics import collect_python_live_metrics

    client = get_native_client()
    python_metrics = collect_python_live_metrics()
    if not client.status().connected:
        if client.resolve_mode() == "enabled":
            raise HTTPException(
                status_code=503,
                detail={"code": "NATIVE_UNAVAILABLE", "message": "Native runtime enabled but not connected."},
            )
        return {"available": False, "fallback_active": True, "metrics": python_metrics}
    try:
        metrics = dict(client.system_metrics() or {})
        # Host identity fields come from Python so the dashboard stays complete
        # even when the companion only reports CPU/memory/uptime.
        for key in ("hostname", "os"):
            if not metrics.get(key) and python_metrics.get(key):
                metrics[key] = python_metrics[key]
        if metrics.get("cpu_percent") is None and python_metrics.get("cpu_percent") is not None:
            metrics["cpu_percent"] = python_metrics["cpu_percent"]
        if not metrics.get("memory") and python_metrics.get("memory"):
            metrics["memory"] = python_metrics["memory"]
        if metrics.get("uptime_ms") is None and python_metrics.get("uptime_ms") is not None:
            metrics["uptime_ms"] = python_metrics["uptime_ms"]
        metrics.setdefault("source", "native")
        return {"available": True, "fallback_active": False, "metrics": metrics}
    except NativeRuntimeError as exc:
        raise HTTPException(status_code=502, detail=exc.as_dict()) from exc


@router.post("/benchmark")
def native_benchmark() -> dict[str, Any]:
    client = get_native_client()
    try:
        if not client.ensure_started() and client.resolve_mode() == "enabled":
            raise NativeRuntimeError("NATIVE_UNAVAILABLE", "Native runtime required but unavailable.")
        if not client.status().connected:
            return {
                "available": False,
                "fallback_active": True,
                "result": None,
                "note": "Native runtime not connected; benchmark skipped.",
            }
        return {"available": True, "fallback_active": False, "result": client.benchmark()}
    except NativeRuntimeError as exc:
        raise HTTPException(status_code=503, detail=exc.as_dict()) from exc
