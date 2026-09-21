"""In-process metrics surface — counters/gauges for operator health, not APM."""

from .collector import MetricsCollector, MetricsSnapshot

__all__ = ["MetricsCollector", "MetricsSnapshot"]
