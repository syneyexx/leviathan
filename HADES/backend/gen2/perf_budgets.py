"""Soft performance budgets for Gen2 characterization (not flake-prone CI gates).

Budgets are recorded and asserted only when timings are far above generous
ceilings — intended for regression alarms on pathological slowness, not
micro-benchmark noise. Use ``record_and_check`` in tests with wall-clock
operations that should finish well under the soft limit on any normal host.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Soft ceilings in milliseconds — intentionally loose (order-of-magnitude).
SOFT_BUDGETS_MS: dict[str, float] = {
    "mission_compile": 2_000.0,
    "context_compile_small": 1_500.0,
    "store_list_missions": 500.0,
    "ir_validate": 200.0,
    "envelope_enforce": 200.0,
}


def budget_ms(name: str) -> float:
    return float(SOFT_BUDGETS_MS.get(name, 5_000.0))


def record_and_check(
    name: str,
    fn: Callable[[], T],
    *,
    soft_ms: float | None = None,
    assert_soft: bool = True,
) -> dict[str, Any]:
    """Run ``fn``, record elapsed ms, optionally assert under soft budget."""
    ceiling = float(soft_ms if soft_ms is not None else budget_ms(name))
    start = perf_counter()
    result = fn()
    elapsed_ms = (perf_counter() - start) * 1000.0
    row = {
        "name": name,
        "elapsed_ms": round(elapsed_ms, 3),
        "soft_budget_ms": ceiling,
        "within_soft_budget": elapsed_ms <= ceiling,
        "flake_prone": False,
        "note": "Soft budget only — not a hard CI flake gate.",
    }
    if assert_soft and elapsed_ms > ceiling:
        raise AssertionError(
            f"perf soft budget exceeded for {name}: {elapsed_ms:.1f}ms > {ceiling:.1f}ms"
        )
    row["result"] = result
    return row
