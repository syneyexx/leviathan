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

    def public_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "passed": self.passed,
            "failed": self.failed,
            "duration_ms": self.duration_ms,
            "steps": [item.public_dict() for item in self.steps],
            "notes": list(self.notes),
            "truth": {
                "mini_soak_is_not_production_slo": True,
                "unmeasured_power_latency_slos": True,
            },
        }


class NeuroSoakHarness:
    """Short local soak loop for neuro contracts. Not a multi-hour SLO claim."""

    def __init__(self) -> None:
        self.telemetry: dict[str, Any] = {"runs": 0, "failures": 0}

    def run(
        self,
        *,
        iterations: int = 3,
        steps: list[tuple[str, Callable[[], str]]] | None = None,
    ) -> SoakReport:
        if iterations < 1:
            raise ValueError("iterations must be >= 1")
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
            notes=(
                "Mini soak only — does not measure power/HBM/p95 under continuous production load",
            ),
        )
