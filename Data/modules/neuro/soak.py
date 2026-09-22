from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class SoakStepResult:
    name: str
    ok: bool
    detail: str
    duration_ms: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class SoakReport:
    iterations: int
    passed: int
    failed: int
    duration_ms: float
    steps: tuple[SoakStepResult, ...]
    notes: tuple[str, ...] = ()
    mode: str = "mini"  # mini | long
    long_soak_enabled: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "passed": self.passed,
            "failed": self.failed,
            "duration_ms": self.duration_ms,
            "steps": [item.public_dict() for item in self.steps],
            "notes": list(self.notes),
            "mode": self.mode,
            "long_soak_enabled": self.long_soak_enabled,
            "truth": {
                "mini_soak_is_not_production_slo": True,
                "long_soak_is_not_multi_hour_slo_claim": True,
                "unmeasured_power_latency_slos": True,
            },
        }


class NeuroSoakHarness:
    """Local soak loop for neuro contracts. Long mode is still not a multi-hour SLO claim."""

    # Hard caps — long soak is extended local exercise, never unbounded.
    MINI_MAX_ITERATIONS = 20
    LONG_MAX_ITERATIONS = 200

    def __init__(self, *, long_soak_enabled: bool = False) -> None:
        self.long_soak_enabled = long_soak_enabled
        self.telemetry: dict[str, Any] = {"runs": 0, "failures": 0, "long_runs": 0}

    def run(
        self,
        *,
        iterations: int = 3,
        steps: list[tuple[str, Callable[[], str]]] | None = None,
        mode: str = "mini",
    ) -> SoakReport:
        if iterations < 1:
            raise ValueError("iterations must be >= 1")
        mode_l = (mode or "mini").strip().lower()
        if mode_l == "long":
            if not self.long_soak_enabled:
                raise ValueError(
                    "long soak requires LEVIATHAN_FEATURE_NEURO_SOAK_LONG=true"
                )
            iterations = min(iterations, self.LONG_MAX_ITERATIONS)
            self.telemetry["long_runs"] += 1
            notes = (
                "Long soak (flag ON) — extended local contract exercise only; "
                "does NOT claim multi-hour power/HBM production SLO",
            )
        else:
            mode_l = "mini"
            iterations = min(iterations, self.MINI_MAX_ITERATIONS)
            notes = (
                "Mini soak only — does not measure power/HBM/p95 under continuous production load",
            )
        self.telemetry["runs"] += 1
        started = time.perf_counter()
        results: list[SoakStepResult] = []
        passed = 0
        failed = 0
        step_defs = steps or []
        for i in range(iterations):
            for name, fn in step_defs:
                step_started = time.perf_counter()
                try:
                    detail = fn()
                    ok = True
                    passed += 1
                except Exception as exc:  # noqa: BLE001
                    detail = str(exc)
                    ok = False
                    failed += 1
                    self.telemetry["failures"] += 1
                results.append(
                    SoakStepResult(
                        name=f"{name}#{i + 1}",
                        ok=ok,
                        detail=detail,
                        duration_ms=(time.perf_counter() - step_started) * 1000,
                    )
                )
        return SoakReport(
            iterations=iterations,
            passed=passed,
            failed=failed,
            duration_ms=(time.perf_counter() - started) * 1000,
            steps=tuple(results),
            notes=notes,
            mode=mode_l,
            long_soak_enabled=self.long_soak_enabled,
        )
