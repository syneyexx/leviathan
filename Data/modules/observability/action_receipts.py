"""Durable autonomous-action telemetry receipts (Wave 17).

Extends ObservabilityHub / JobRecord — does not invent a parallel telemetry bus.
Every durable autonomous action should emit a receipt with the closed field set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

REQUIRED_RECEIPT_FIELDS: tuple[str, ...] = (
    "trace_id",
    "job_id",
    "root_job_id",
    "domain_entity_type",
    "domain_entity_id",
    "worker_pool",
    "resource_class",
    "queue_latency_ms",
    "runtime_ms",
    "retries",
    "result_state",
    "error_code",
    "artifact_refs",
)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _latency_ms(start: str | None, end: str | None) -> float | None:
    a = _parse_ts(start)
    b = _parse_ts(end)
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds() * 1000.0)


@dataclass(frozen=True)
class ActionTelemetryReceipt:
    """Consistent receipt emitted for durable autonomous / worker actions."""

    trace_id: str | None
    job_id: str
    root_job_id: str | None
    domain_entity_type: str | None
    domain_entity_id: str | None
    worker_pool: str | None
    resource_class: str | None
    queue_latency_ms: float | None
    runtime_ms: float | None
    retries: int
    result_state: str
    error_code: str | None
    artifact_refs: tuple[str, ...] = ()
    capability_id: str | None = None
    correlation_id: str | None = None
    attempt_number: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "job_id": self.job_id,
            "root_job_id": self.root_job_id or self.job_id,
            "domain_entity_type": self.domain_entity_type,
            "domain_entity_id": self.domain_entity_id,
            "worker_pool": self.worker_pool,
            "resource_class": self.resource_class,
            "queue_latency_ms": self.queue_latency_ms,
            "runtime_ms": self.runtime_ms,
            "retries": int(self.retries),
            "result_state": self.result_state,
            "error_code": self.error_code,
            "artifact_refs": list(self.artifact_refs),
            "capability_id": self.capability_id,
            "correlation_id": self.correlation_id,
            "attempt_number": int(self.attempt_number),
            "metadata": dict(self.metadata),
            "truth": {
                "receipt_is_not_authorization": True,
                "extends_observability_hub": True,
                "required_fields": list(REQUIRED_RECEIPT_FIELDS),
            },
        }

    def missing_fields(self) -> list[str]:
        payload = self.public_dict()
        missing: list[str] = []
        for key in REQUIRED_RECEIPT_FIELDS:
            val = payload.get(key)
            if val is None:
                missing.append(key)
            elif key == "artifact_refs" and not isinstance(val, list):
                missing.append(key)
        return missing


def receipt_from_job(
    job: Any,
    *,
    runtime_ms: float | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> ActionTelemetryReceipt:
    """Build a receipt from a JobRecord (or duck-typed job)."""
    state = getattr(job, "state", None)
    result_state = getattr(state, "value", None) or getattr(state, "name", None) or str(state or "UNKNOWN")
    queued_at = getattr(job, "queued_at", None) or getattr(job, "created_at", None)
    claimed_at = getattr(job, "claimed_at", None) or getattr(job, "started_at", None)
    started_at = getattr(job, "started_at", None) or claimed_at
    finished_at = getattr(job, "finished_at", None)
    queue_latency = _latency_ms(queued_at, claimed_at)
    measured_runtime = runtime_ms if runtime_ms is not None else _latency_ms(started_at, finished_at)
    attempt = int(getattr(job, "attempt_number", 1) or 1)
    retries = max(0, attempt - 1)
    refs_raw = getattr(job, "artifact_refs", None) or []
    refs = tuple(str(r) for r in refs_raw if r is not None)
    meta = dict(getattr(job, "metadata", None) or {})
    if extra_metadata:
        meta.update(dict(extra_metadata))
    return ActionTelemetryReceipt(
        trace_id=getattr(job, "trace_id", None) or getattr(job, "correlation_id", None),
        job_id=str(getattr(job, "job_id", "") or ""),
        root_job_id=getattr(job, "root_job_id", None),
        domain_entity_type=getattr(job, "domain_entity_type", None),
        domain_entity_id=getattr(job, "domain_entity_id", None),
        worker_pool=getattr(job, "worker_pool", None),
        resource_class=getattr(job, "resource_class", None),
        queue_latency_ms=queue_latency,
        runtime_ms=measured_runtime,
        retries=retries,
        result_state=str(result_state),
        error_code=getattr(job, "error_code", None),
        artifact_refs=refs,
        capability_id=getattr(job, "capability_id", None),
        correlation_id=getattr(job, "correlation_id", None),
        attempt_number=attempt,
        metadata=meta,
    )


def emit_action_receipt(
    hub: Any,
    job: Any,
    *,
    runtime_ms: float | None = None,
    level: str = "info",
    name: str = "autonomous_action_receipt",
) -> dict[str, Any]:
    """Emit receipt through ObservabilityHub when available; always return dict."""
    receipt = receipt_from_job(job, runtime_ms=runtime_ms)
    payload = receipt.public_dict()
    if hub is not None and hasattr(hub, "emit"):
        try:
            hub.emit(
                "workers",
                name,
                payload=payload,
                level=level if receipt.result_state not in {"FAILED", "CANCELLED"} else "error",
                job_id=receipt.job_id,
                correlation_id=receipt.correlation_id or receipt.trace_id,
                capability_id=receipt.capability_id,
                duration_ms=receipt.runtime_ms,
                success=receipt.result_state == "COMPLETED",
                message=f"action_receipt:{receipt.job_id}:{receipt.result_state}",
            )
        except Exception:  # noqa: BLE001 — telemetry must never break workers
            payload["emit_error"] = "hub_emit_failed"
    return payload
