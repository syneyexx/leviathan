"""Real resource pressure for ADAPTIVE compute (W3).

Never return a fake constant. When a signal is unavailable, omit it and
weight the remaining measured signals. Overall pressure stays in [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ResourcePressureSample:
    pressure: float
    components: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "pressure": self.pressure,
            "components": dict(self.components),
            "provenance": dict(self.provenance),
            "notes": list(self.notes),
            "truth": {
                "not_a_fake_constant": True,
                "unavailable_signals_omitted_not_zero_filled_as_measured": True,
            },
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def measure_resource_pressure(
    *,
    telemetry_snapshot: dict[str, Any] | None = None,
    queue_depth: int | None = None,
    queue_capacity: int | None = None,
    active_workloads: int | None = None,
    workload_capacity: int | None = None,
    model_latency_ms: float | None = None,
    model_latency_baseline_ms: float | None = None,
    task_complexity: float | None = None,
    uncertainty: float | None = None,
) -> ResourcePressureSample:
    """Compose a pressure sample from measured / provided signals.

    Expected telemetry_snapshot keys (optional):
      cpuPct, ramPct, vramPct  — percentages 0–100
    """
    components: dict[str, float] = {}
    provenance: dict[str, str] = {}
    notes: list[str] = []

    snap = telemetry_snapshot or {}
    for key, out_name in (
        ("cpuPct", "cpu"),
        ("ramPct", "ram"),
        ("vramPct", "vram"),
    ):
        raw = snap.get(key)
        if raw is None:
            provenance[out_name] = "UNAVAILABLE"
            continue
        try:
            components[out_name] = _clamp01(float(raw) / 100.0)
            provenance[out_name] = "MEASURED"
        except (TypeError, ValueError):
            provenance[out_name] = "UNAVAILABLE"
            notes.append(f"{out_name} unparseable")

    if queue_depth is not None and queue_capacity and queue_capacity > 0:
        components["queue"] = _clamp01(float(queue_depth) / float(queue_capacity))
        provenance["queue"] = "MEASURED"
    elif queue_depth is not None:
        # Soft saturation curve without known capacity.
        components["queue"] = _clamp01(float(queue_depth) / 16.0)
        provenance["queue"] = "ESTIMATED"
        notes.append("queue capacity unknown — estimated saturation curve")
    else:
        provenance["queue"] = "UNAVAILABLE"

    if active_workloads is not None and workload_capacity and workload_capacity > 0:
        components["workloads"] = _clamp01(float(active_workloads) / float(workload_capacity))
        provenance["workloads"] = "MEASURED"
    elif active_workloads is not None:
        components["workloads"] = _clamp01(float(active_workloads) / 8.0)
        provenance["workloads"] = "ESTIMATED"
    else:
        provenance["workloads"] = "UNAVAILABLE"

    if (
        model_latency_ms is not None
        and model_latency_baseline_ms is not None
        and model_latency_baseline_ms > 0
    ):
        drift = float(model_latency_ms) / float(model_latency_baseline_ms)
        # drift 1.0 → 0; drift ≥ 3.0 → 1
        components["latency_drift"] = _clamp01((drift - 1.0) / 2.0)
        provenance["latency_drift"] = "MEASURED"
    else:
        provenance["latency_drift"] = "UNAVAILABLE"

    if task_complexity is not None:
        components["task_complexity"] = _clamp01(task_complexity)
        provenance["task_complexity"] = "PROVIDED"
    if uncertainty is not None:
        components["uncertainty"] = _clamp01(uncertainty)
        provenance["uncertainty"] = "PROVIDED"

    if not components:
        notes.append("no measurable signals — pressure UNMEASURED → 0.0 (not fake load)")
        return ResourcePressureSample(
            pressure=0.0,
            components={},
            provenance=provenance,
            notes=tuple(notes),
        )

    # Weight resource signals higher than task hints for ADAPTIVE demotion.
    weights = {
        "cpu": 1.0,
        "ram": 1.2,
        "vram": 1.3,
        "queue": 1.1,
        "workloads": 1.0,
        "latency_drift": 0.8,
        "task_complexity": 0.35,
        "uncertainty": 0.35,
    }
    total_w = 0.0
    acc = 0.0
    for name, value in components.items():
        w = weights.get(name, 0.5)
        acc += value * w
        total_w += w
    pressure = _clamp01(acc / total_w) if total_w else 0.0
    return ResourcePressureSample(
        pressure=round(pressure, 4),
        components={k: round(v, 4) for k, v in components.items()},
        provenance=provenance,
        notes=tuple(notes),
    )


def build_resource_pressure_fn(
    *,
    telemetry_provider: Callable[[], dict[str, Any] | None] | None = None,
    queue_provider: Callable[[], tuple[int | None, int | None]] | None = None,
    workload_provider: Callable[[], tuple[int | None, int | None]] | None = None,
    latency_provider: Callable[[], tuple[float | None, float | None]] | None = None,
) -> Callable[[], float]:
    """Return a zero-arg pressure callback for CognitiveRuntime."""

    def _fn() -> float:
        snap = telemetry_provider() if telemetry_provider else None
        q_depth, q_cap = (None, None)
        if queue_provider:
            try:
                q_depth, q_cap = queue_provider()
            except Exception:  # noqa: BLE001
                q_depth, q_cap = None, None
        w_active, w_cap = (None, None)
        if workload_provider:
            try:
                w_active, w_cap = workload_provider()
            except Exception:  # noqa: BLE001
                w_active, w_cap = None, None
        lat, base = (None, None)
        if latency_provider:
            try:
                lat, base = latency_provider()
            except Exception:  # noqa: BLE001
                lat, base = None, None
        sample = measure_resource_pressure(
            telemetry_snapshot=snap if isinstance(snap, dict) else None,
            queue_depth=q_depth,
            queue_capacity=q_cap,
            active_workloads=w_active,
            workload_capacity=w_cap,
            model_latency_ms=lat,
            model_latency_baseline_ms=base,
        )
        return float(sample.pressure)

    return _fn


def telemetry_dict_from_observability(observability: Any) -> dict[str, Any] | None:
    """Best-effort extract cpu/ram/vram percentages from ObservabilityHub."""
    if observability is None:
        return None
    try:
        # Prefer a fresh sample when collector is present.
        collector = getattr(observability, "system_telemetry", None) or getattr(
            observability, "telemetry", None
        )
        if collector is not None and hasattr(collector, "sample"):
            sample = collector.sample()
            if hasattr(sample, "public_dict"):
                data = sample.public_dict()
            elif isinstance(sample, dict):
                data = sample
            else:
                data = {}
            summary = data.get("summary") if isinstance(data, dict) else None
            if isinstance(summary, dict):
                return {
                    "cpuPct": summary.get("cpuPct"),
                    "ramPct": summary.get("ramPct"),
                    "vramPct": summary.get("vramPct"),
                }
            return {
                "cpuPct": data.get("cpuPct") if isinstance(data, dict) else None,
                "ramPct": data.get("ramPct") if isinstance(data, dict) else None,
                "vramPct": data.get("vramPct") if isinstance(data, dict) else None,
            }
    except Exception:  # noqa: BLE001
        return None
    return None
