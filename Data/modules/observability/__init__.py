"""Observability — durable events, live stream, system telemetry."""

from .hub import ObservabilityHub, TelemetryEvent, normalize_level
from .event_store import EventStore
from .operator import OperatorCommandRegistry, OperatorCommandResult, build_default_operator_registry
from .otel import FixtureOtelExporter, SpanRecord
from .redaction import redact_payload, redact_value
from .slo import SloDefinition, SloEvaluation, SloRegistry, default_production_slos
from .stream import EventStreamBroker
from .system_telemetry import (
    SystemTelemetrySample,
    SystemTelemetrySampler,
    collect_system_sample,
    parse_nvidia_smi_csv,
    probe_nvidia_smi,
)

__all__ = [
    "ObservabilityHub",
    "TelemetryEvent",
    "normalize_level",
    "EventStore",
    "EventStreamBroker",
    "FixtureOtelExporter",
    "SpanRecord",
    "SloDefinition",
    "SloEvaluation",
    "SloRegistry",
    "default_production_slos",
    "OperatorCommandRegistry",
    "OperatorCommandResult",
    "build_default_operator_registry",
    "redact_payload",
    "redact_value",
    "SystemTelemetrySample",
    "SystemTelemetrySampler",
    "collect_system_sample",
    "parse_nvidia_smi_csv",
    "probe_nvidia_smi",
]
