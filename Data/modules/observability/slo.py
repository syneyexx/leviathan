"""Service-level objectives over local metrics (U343).

SLOs are evaluated from in-process samples — not a cloud alerting product.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SloDefinition:
    slo_id: str
    name: str
    objective: float  # e.g. 0.99 success ratio
    window_samples: int = 50
    metric: str = "success_ratio"
    description: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "slo_id": self.slo_id,
            "name": self.name,
            "objective": self.objective,
            "window_samples": self.window_samples,
            "metric": self.metric,
            "description": self.description,
            "truth": {
                "slo_is_local_evaluation": True,
                "not_cloud_alerting_product": True,
            },
        }


@dataclass(frozen=True)
class SloSample:
    success: bool
    latency_ms: float | None = None
    recorded_at_ms: float = 0.0
    labels: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SloEvaluation:
    slo_id: str
    sample_count: int
    success_ratio: float
    objective: float
    met: bool
    burn_hint: str
    evaluated_at_ms: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "slo_id": self.slo_id,
            "sample_count": self.sample_count,
            "success_ratio": self.success_ratio,
            "objective": self.objective,
            "met": self.met,
            "burn_hint": self.burn_hint,
            "evaluated_at_ms": self.evaluated_at_ms,
        }


class SloRegistry:
    """Define and evaluate local SLOs from recorded samples."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._defs: dict[str, SloDefinition] = {}
        self._samples: dict[str, list[SloSample]] = {}

    def register(self, definition: SloDefinition) -> SloDefinition:
        with self._lock:
            self._defs[definition.slo_id] = definition
            self._samples.setdefault(definition.slo_id, [])
        return definition

    def record(
        self,
        slo_id: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        labels: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            definition = self._defs.get(slo_id)
            bucket = self._samples.setdefault(slo_id, [])
            bucket.append(
                SloSample(
                    success=success,
                    latency_ms=latency_ms,
                    recorded_at_ms=time.time() * 1000,
                    labels=dict(labels or {}),
                )
            )
            window = definition.window_samples if definition else 100
            if len(bucket) > window * 2:
                del bucket[: len(bucket) - window]

    def evaluate(self, slo_id: str) -> SloEvaluation:
        with self._lock:
            definition = self._defs.get(slo_id)
            if definition is None:
                raise KeyError(f"Unknown SLO: {slo_id}")
            samples = list(self._samples.get(slo_id, []))[-definition.window_samples :]
        if not samples:
            return SloEvaluation(
                slo_id=slo_id,
                sample_count=0,
                success_ratio=0.0,
                objective=definition.objective,
                met=False,
                burn_hint="insufficient_samples",
                evaluated_at_ms=time.time() * 1000,
            )
        successes = sum(1 for s in samples if s.success)
        ratio = successes / len(samples)
        met = ratio >= definition.objective
        burn = "healthy" if met else ("error_budget_burning" if ratio >= definition.objective * 0.9 else "breach")
        return SloEvaluation(
            slo_id=slo_id,
            sample_count=len(samples),
            success_ratio=ratio,
            objective=definition.objective,
            met=met,
            burn_hint=burn,
            evaluated_at_ms=time.time() * 1000,
        )

    def list_definitions(self) -> list[SloDefinition]:
        with self._lock:
            return list(self._defs.values())

    def public_dict(self) -> dict[str, Any]:
        return {
            "slos": [d.public_dict() for d in self.list_definitions()],
            "truth": {
                "slo_is_local_evaluation": True,
                "not_cloud_alerting_product": True,
            },
        }


def default_production_slos() -> list[SloDefinition]:
    return [
        SloDefinition(
            slo_id="gateway_success",
            name="Gateway success ratio",
            objective=0.95,
            window_samples=40,
            description="Capability executions completing without FAILED status",
        ),
        SloDefinition(
            slo_id="job_recovery",
            name="Job recovery success",
            objective=0.90,
            window_samples=20,
            description="Expired-lease reclaim completing without duplicate effects",
        ),
    ]
