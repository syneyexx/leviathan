"""Chaos scenario presets for fault-injection / recovery tests (U354)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .injector import ChaosInjector, ChaosPlan


@dataclass(frozen=True)
class ChaosScenario:
    scenario_id: str
    name: str
    description: str
    plan: ChaosPlan
    hooks: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "plan": self.plan.public_dict(),
            "hooks": list(self.hooks),
            "truth": {
                "chaos_default_off": True,
                "chaos_is_not_production_mode": True,
            },
        }


SCENARIOS: dict[str, ChaosScenario] = {
    "kill_worker": ChaosScenario(
        scenario_id="kill_worker",
        name="Kill worker mid-lease",
        description="Simulate worker death; recovery must reclaim lease without duplicate effects",
        plan=ChaosPlan(enabled=True, latency_ms=0, error_rate=1.0, error_message="chaos_kill_worker"),
        hooks=("mark_worker_dead", "expire_lease"),
    ),
    "expire_lease": ChaosScenario(
        scenario_id="expire_lease",
        name="Expire job lease",
        description="Force lease expiry so takeover path runs",
        plan=ChaosPlan(enabled=True, latency_ms=0, error_rate=0.0),
        hooks=("expire_lease",),
    ),
    "provider_timeout": ChaosScenario(
        scenario_id="provider_timeout",
        name="Provider timeout",
        description="Inject latency + error for provider loss",
        plan=ChaosPlan(
            enabled=True,
            latency_ms=25,
            error_rate=1.0,
            error_message="chaos_provider_timeout",
        ),
        hooks=("provider_fault",),
    ),
    "disk_pressure": ChaosScenario(
        scenario_id="disk_pressure",
        name="Disk pressure",
        description="Simulate artifact write failure under disk pressure",
        plan=ChaosPlan(
            enabled=True,
            latency_ms=5,
            error_rate=1.0,
            error_message="chaos_disk_pressure",
        ),
        hooks=("artifact_write_fault",),
    ),
}


class ChaosScenarioRunner:
    """Apply named scenarios onto a ChaosInjector (+ optional hooks)."""

    def __init__(self, injector: ChaosInjector) -> None:
        self.injector = injector
        self.active_scenario: str | None = None
        self._hooks: dict[str, Callable[[], None]] = {}

    def register_hook(self, name: str, fn: Callable[[], None]) -> None:
        self._hooks[name] = fn

    def list_scenarios(self) -> list[ChaosScenario]:
        return list(SCENARIOS.values())

    def apply(self, scenario_id: str, *, run_hooks: bool = True) -> ChaosScenario:
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            raise KeyError(f"Unknown chaos scenario: {scenario_id}")
        self.injector.configure(scenario.plan)
        self.active_scenario = scenario_id
        if run_hooks:
            for hook in scenario.hooks:
                fn = self._hooks.get(hook)
                if fn is not None:
                    fn()
        return scenario

    def disable(self) -> None:
        self.injector.configure(ChaosPlan(enabled=False))
        self.active_scenario = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "active_scenario": self.active_scenario,
            "scenarios": [s.public_dict() for s in self.list_scenarios()],
            "injector": self.injector.public_dict(),
        }
