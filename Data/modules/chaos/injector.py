from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChaosPlan:
    enabled: bool = False
    latency_ms: int = 0
    error_rate: float = 0.0
    error_message: str = "chaos_injected_failure"

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "latency_ms": self.latency_ms,
            "error_rate": self.error_rate,
            "error_message": self.error_message,
            "truth": {
                "chaos_default_off": True,
                "chaos_is_not_production_mode": True,
            },
        }


class ChaosInjector:
    """Optional fault injection for local resilience tests.

    When disabled (default), ``maybe_fault`` is a no-op.
    """

    def __init__(self, plan: ChaosPlan | None = None) -> None:
        self._plan = plan or ChaosPlan()
        self.activations = 0
        self.faults = 0

    @property
    def plan(self) -> ChaosPlan:
        return self._plan

    def configure(self, plan: ChaosPlan) -> ChaosPlan:
        self._plan = plan
        return self._plan

    def maybe_fault(self, *, rng: random.Random | None = None) -> None:
        plan = self._plan
        if not plan.enabled:
            return
        self.activations += 1
        if plan.latency_ms > 0:
            time.sleep(plan.latency_ms / 1000.0)
        rate = max(0.0, min(plan.error_rate, 1.0))
        roller = rng or random
        if rate > 0 and roller.random() < rate:
            self.faults += 1
            raise RuntimeError(plan.error_message)

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan": self._plan.public_dict(),
            "activations": self.activations,
            "faults": self.faults,
        }
