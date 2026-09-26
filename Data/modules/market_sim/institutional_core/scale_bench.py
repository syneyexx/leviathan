"""W71 — Institutional scale benchmarks (extends scale_smoke honesty)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass
class BenchCase:
    case_id: str
    n: int
    description: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {"caseId": self.case_id, "n": self.n, "description": self.description}


@dataclass
class BenchResult:
    case_id: str
    n: int
    elapsed_sec: float
    ok: bool
    status: str
    fingerprint: str
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "caseId": self.case_id,
            "n": self.n,
            "elapsedSec": self.elapsed_sec,
            "ok": self.ok,
            "status": self.status,
            "fingerprint": self.fingerprint,
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "bench_is_not_full_production_capacity_claim": True,
                "extends_scale_smoke": True,
            },
        }


DEFAULT_BENCH_CASES: tuple[BenchCase, ...] = (
    BenchCase("smoke_1k", 1_000, "tiny smoke"),
    BenchCase("smoke_50k", 50_000, "medium smoke"),
    BenchCase("smoke_200k", 200_000, "larger smoke — still not multi-year market replay"),
)


def run_bench_case(
    case: BenchCase,
    *,
    work: Callable[[int], Any] | None = None,
    budget_sec: float = 5.0,
) -> BenchResult:
    """Prefer institutional_ops.scale_smoke when available."""
    notes: list[str] = ["not_full_5y_benchmark"]
    try:
        from ..institutional_ops import scale_smoke

        raw = scale_smoke(n=case.n, work=work)
        elapsed = float(raw.get("elapsedSec") or 0)
        ok = bool(raw.get("ok"))
        # Re-evaluate against local budget if provided differently.
        if budget_sec != 5.0:
            ok = elapsed < budget_sec
        return BenchResult(
            case_id=case.case_id,
            n=case.n,
            elapsed_sec=elapsed,
            ok=ok,
            status=MeasurementState.OBSERVED.value if ok else MeasurementState.FAIL.value,
            fingerprint=str(raw.get("resultFingerprint") or ""),
            notes=notes,
        )
    except Exception:  # noqa: BLE001
        start = time.perf_counter()
        if work is None:
            total = sum(range(case.n))
        else:
            total = work(case.n)
        elapsed = time.perf_counter() - start
        ok = elapsed < budget_sec
        return BenchResult(
            case_id=case.case_id,
            n=case.n,
            elapsed_sec=elapsed,
            ok=ok,
            status=MeasurementState.OBSERVED.value if ok else MeasurementState.FAIL.value,
            fingerprint=str(total)[:64],
            notes=notes + ["fallback_timer"],
        )


def run_scale_bench(
    cases: Sequence[BenchCase] = DEFAULT_BENCH_CASES,
    *,
    work: Callable[[int], Any] | None = None,
    budget_sec: float = 5.0,
) -> dict[str, Any]:
    results = [run_bench_case(c, work=work, budget_sec=budget_sec) for c in cases]
    all_ok = all(r.ok for r in results)
    return {
        "results": [r.public_dict() for r in results],
        "ok": all_ok,
        "status": MeasurementState.OBSERVED.value if all_ok else MeasurementState.FAIL.value,
        "truth": {
            **DEFAULT_TRUTH.public_dict(),
            "smoke_is_not_full_5y_benchmark": True,
        },
    }
