"""OpenTelemetry-compatible fixture trace exporter (U342).

No third-party OTel SDK required — spans are in-memory and exportable as
OTLP-shaped dicts. Real OTLP HTTP/gRPC adapters remain optional.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpanRecord:
    trace_id: str
    span_id: str
    name: str
    start_ms: float
    end_ms: float | None = None
    parent_span_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "UNSET"
    events: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": (self.end_ms - self.start_ms) if self.end_ms is not None else None,
            "attributes": self.attributes,
            "status": self.status,
            "events": list(self.events),
            "truth": {
                "fixture_otel_not_full_sdk": True,
                "otlp_http_unmeasured": True,
            },
        }


class FixtureOtelExporter:
    """In-process span store — exportable as OTLP-shaped JSON."""

    def __init__(self, *, max_spans: int = 5_000) -> None:
        self.max_spans = max(100, int(max_spans))
        self._lock = threading.RLock()
        self._spans: list[SpanRecord] = []
        self._active: dict[str, SpanRecord] = {}

    def start_span(
        self,
        name: str,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanRecord:
        span = SpanRecord(
            trace_id=trace_id or uuid.uuid4().hex,
            span_id=uuid.uuid4().hex[:16],
            name=name,
            start_ms=time.time() * 1000,
            parent_span_id=parent_span_id,
            attributes=dict(attributes or {}),
        )
        with self._lock:
            self._active[span.span_id] = span
            self._spans.append(span)
            if len(self._spans) > self.max_spans:
                self._spans = self._spans[-self.max_spans :]
        return span

    def end_span(self, span_id: str, *, status: str = "OK", attributes: dict[str, Any] | None = None) -> SpanRecord | None:
        with self._lock:
            span = self._active.pop(span_id, None)
            if span is None:
                for candidate in reversed(self._spans):
                    if candidate.span_id == span_id:
                        span = candidate
                        break
            if span is None:
                return None
            if attributes:
                span.attributes.update(attributes)
            span.end_ms = time.time() * 1000
            span.status = status
            return span

    def add_event(self, span_id: str, name: str, *, attributes: dict[str, Any] | None = None) -> None:
        with self._lock:
            span = self._active.get(span_id)
            if span is None:
                return
            span.events.append(
                {
                    "name": name,
                    "timestamp_ms": time.time() * 1000,
                    "attributes": dict(attributes or {}),
                }
            )

    def list_spans(self, *, trace_id: str | None = None, limit: int = 100) -> list[SpanRecord]:
        with self._lock:
            spans = list(self._spans)
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return spans[-max(1, min(limit, 1000)) :]

    def export_otlp_shaped(self, *, limit: int = 100) -> dict[str, Any]:
        spans = self.list_spans(limit=limit)
        return {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": s.trace_id,
                                    "spanId": s.span_id,
                                    "parentSpanId": s.parent_span_id,
                                    "name": s.name,
                                    "startTimeUnixNano": int((s.start_ms or 0) * 1_000_000),
                                    "endTimeUnixNano": int((s.end_ms or s.start_ms or 0) * 1_000_000),
                                    "attributes": [
                                        {"key": k, "value": {"stringValue": str(v)}}
                                        for k, v in s.attributes.items()
                                    ],
                                    "status": {"code": s.status},
                                }
                                for s in spans
                            ]
                        }
                    ]
                }
            ],
            "truth": {
                "fixture_otlp_shape_not_network_export": True,
                "sdk_dependency_not_required": True,
            },
        }

    def public_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "span_count": len(self._spans),
                "active_count": len(self._active),
                "truth": {
                    "fixture_otel_not_full_sdk": True,
                    "otlp_http_unmeasured": True,
                },
            }
