"""Observability hub — ring buffer + durable history + live fan-out."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .event_store import EventStore
from .redaction import redact_payload
from .stream import EventStreamBroker

_LEVEL_ALIASES = {
    "debug": "DEBUG",
    "info": "INFO",
    "success": "SUCCESS",
    "ok": "SUCCESS",
    "warn": "WARNING",
    "warning": "WARNING",
    "error": "ERROR",
    "err": "ERROR",
    "critical": "CRITICAL",
    "fatal": "CRITICAL",
}

_ENTITY_KEYS = (
    "request_id",
    "correlation_id",
    "parent_correlation_id",
    "actor",
    "run_id",
    "job_id",
    "workflow_id",
    "workflow_run_id",
    "workflow_step_id",
    "module_id",
    "mcp_server_id",
    "tool_id",
    "capability_id",
    "research_project_id",
    "dataset_id",
    "evidence_id",
    "duration_ms",
    "success",
    "source",
    "message",
    "subsystem",
)


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    category: str
    name: str
    created_at_ms: float
    payload: dict[str, Any] = field(default_factory=dict)
    level: str = "INFO"
    sequence: int = 0
    subsystem: str = ""
    message: str = ""
    source: str = ""
    request_id: str | None = None
    correlation_id: str | None = None
    parent_correlation_id: str | None = None
    actor: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    workflow_step_id: str | None = None
    module_id: str | None = None
    mcp_server_id: str | None = None
    tool_id: str | None = None
    capability_id: str | None = None
    research_project_id: str | None = None
    dataset_id: str | None = None
    evidence_id: str | None = None
    duration_ms: float | None = None
    success: bool | None = None
    redacted: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_id": self.event_id,
            "created_at_ms": self.created_at_ms,
            "level": self.level,
            "category": self.category,
            "subsystem": self.subsystem or self.category,
            "name": self.name,
            "message": self.message,
            "payload": self.payload,
            "source": self.source,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "parent_correlation_id": self.parent_correlation_id,
            "actor": self.actor,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "workflow_id": self.workflow_id,
            "workflow_run_id": self.workflow_run_id,
            "workflow_step_id": self.workflow_step_id,
            "module_id": self.module_id,
            "mcp_server_id": self.mcp_server_id,
            "tool_id": self.tool_id,
            "capability_id": self.capability_id,
            "research_project_id": self.research_project_id,
            "dataset_id": self.dataset_id,
            "evidence_id": self.evidence_id,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "redacted": self.redacted,
        }


def normalize_level(level: str | None) -> str:
    if not level:
        return "INFO"
    return _LEVEL_ALIASES.get(str(level).strip().lower(), str(level).strip().upper() or "INFO")


class ObservabilityHub:
    """Canonical runtime event authority: ring buffer + durable store + SSE broker."""

    def __init__(
        self,
        *,
        capacity: int = 500,
        db_path: Path | None = None,
        max_durable_rows: int = 50_000,
        retention_days: int = 14,
        persist: bool = True,
    ) -> None:
        if capacity < 10:
            raise ValueError("capacity must be >= 10")
        self.capacity = capacity
        self._events: deque[TelemetryEvent] = deque(maxlen=capacity)
        self._lock = threading.RLock()
        self.counters: dict[str, int] = {}
        self._sequence = 0
        self.broker = EventStreamBroker()
        self.store: EventStore | None = None
        if persist and db_path is not None:
            self.store = EventStore(
                Path(db_path),
                max_rows=max_durable_rows,
                retention_days=retention_days,
            )
            self.store.initialize()
            self._sequence = self.store.latest_sequence()

    def emit(
        self,
        category: str,
        name: str,
        *,
        payload: dict[str, Any] | None = None,
        level: str = "info",
        message: str | None = None,
        source: str | None = None,
        subsystem: str | None = None,
        correlation_id: str | None = None,
        request_id: str | None = None,
        parent_correlation_id: str | None = None,
        actor: str | None = None,
        duration_ms: float | None = None,
        success: bool | None = None,
        **entity_ids: Any,
    ) -> TelemetryEvent:
        raw_payload = dict(payload or {})
        # Pull known entity fields from kwargs or payload (kwargs win).
        extracted: dict[str, Any] = {}
        for key in _ENTITY_KEYS:
            if key in entity_ids and entity_ids[key] is not None:
                extracted[key] = entity_ids[key]
            elif key in raw_payload and raw_payload[key] is not None and key not in extracted:
                extracted[key] = raw_payload[key]

        safe_payload = redact_payload(raw_payload)
        level_n = normalize_level(level)
        msg = message if message is not None else extracted.get("message")
        if not msg:
            msg = f"{category}.{name}"

        event_id = str(uuid.uuid4())
        created_at_ms = time.time() * 1000
        base_fields = dict(
            event_id=event_id,
            category=category,
            name=name,
            created_at_ms=created_at_ms,
            payload=safe_payload,
            level=level_n,
            subsystem=str(subsystem or extracted.get("subsystem") or category),
            message=str(msg),
            source=str(source or extracted.get("source") or "leviathan"),
            request_id=_opt_str(request_id or extracted.get("request_id")),
            correlation_id=_opt_str(correlation_id or extracted.get("correlation_id")),
            parent_correlation_id=_opt_str(
                parent_correlation_id or extracted.get("parent_correlation_id")
            ),
            actor=_opt_str(actor or extracted.get("actor")),
            run_id=_opt_str(extracted.get("run_id")),
            job_id=_opt_str(extracted.get("job_id")),
            workflow_id=_opt_str(extracted.get("workflow_id")),
            workflow_run_id=_opt_str(extracted.get("workflow_run_id")),
            workflow_step_id=_opt_str(extracted.get("workflow_step_id")),
            module_id=_opt_str(extracted.get("module_id")),
            mcp_server_id=_opt_str(extracted.get("mcp_server_id")),
            tool_id=_opt_str(extracted.get("tool_id")),
            capability_id=_opt_str(extracted.get("capability_id")),
            research_project_id=_opt_str(extracted.get("research_project_id")),
            dataset_id=_opt_str(extracted.get("dataset_id")),
            evidence_id=_opt_str(extracted.get("evidence_id")),
            duration_ms=_opt_float(
                duration_ms if duration_ms is not None else extracted.get("duration_ms")
            ),
            success=_opt_bool(success if success is not None else extracted.get("success")),
            redacted=True,
        )

        sequence = 0
        persist_error: str | None = None
        if self.store is not None:
            try:
                sequence = self.store.append({**base_fields, "sequence": 0})
            except Exception as exc:  # noqa: BLE001 — hub must not crash emitters
                persist_error = type(exc).__name__

        with self._lock:
            if sequence <= 0:
                self._sequence += 1
                sequence = self._sequence
            else:
                self._sequence = max(self._sequence, sequence)
            if persist_error:
                base_fields["payload"] = {**safe_payload, "_persist_error": persist_error}
            event = TelemetryEvent(sequence=sequence, **base_fields)
            self._events.append(event)
            key = f"{category}.{name}"
            self.counters[key] = self.counters.get(key, 0) + 1
            public = event.public_dict()

        try:
            self.broker.publish(public)
        except Exception:
            pass
        return event

    def recent(
        self,
        *,
        limit: int = 50,
        category: str | None = None,
        level: str | None = None,
    ) -> list[TelemetryEvent]:
        with self._lock:
            items = list(self._events)
        if category:
            items = [item for item in items if item.category == category]
        if level:
            lvl = normalize_level(level)
            items = [item for item in items if item.level == lvl]
        return list(reversed(items[-max(1, min(limit, self.capacity)) :]))

    def query_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        if self.store is None:
            # Fall back to ring buffer projection
            events = self.recent(limit=int(kwargs.get("limit") or 100))
            return [e.public_dict() for e in events]
        return self.store.query(**kwargs)

    def events_after(self, sequence: int, *, limit: int = 200) -> list[dict[str, Any]]:
        if self.store is not None:
            return self.store.get_after(sequence, limit=limit)
        with self._lock:
            items = [e.public_dict() for e in self._events if e.sequence > sequence]
        return items[:limit]

    def latest_sequence(self) -> int:
        if self.store is not None:
            return self.store.latest_sequence()
        with self._lock:
            return self._sequence

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = {
                "capacity": self.capacity,
                "buffered": len(self._events),
                "counters": dict(sorted(self.counters.items())),
                "latest_sequence": self._sequence,
                "subscribers": self.broker.subscriber_count(),
                "durable": self.store is not None,
            }
        if self.store is not None:
            snap["durable_latest_sequence"] = self.store.latest_sequence()
            snap["level_counts"] = self.store.counts_by_level()
        return snap

    def shutdown(self) -> None:
        self.broker.shutdown()


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "ok", "success"}:
        return True
    if text in {"0", "false", "no", "error", "fail", "failed"}:
        return False
    return None
