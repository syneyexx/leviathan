"""Paired evaluation — BASELINE vs LEVIATHAN on the same tasks.

Does not hide regressions behind one aggregate score.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .assistant_benchmark import (
    AssistantBenchmarkRunner,
    AssistantTask,
    TaskRunResult,
    default_assistant_tasks,
)


@dataclass(frozen=True)
class PairedTaskDelta:
    task_id: str
    family: str
    baseline_success: bool
    leviathan_success: bool
    improved: bool
    regressed: bool
    baseline_metrics: dict[str, Any]
    leviathan_metrics: dict[str, Any]
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "family": self.family,
            "baseline_success": self.baseline_success,
            "leviathan_success": self.leviathan_success,
            "improved": self.improved,
            "regressed": self.regressed,
            "baseline_metrics": dict(self.baseline_metrics),
            "leviathan_metrics": dict(self.leviathan_metrics),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PairedEvaluationReport:
    report_id: str
    deltas: tuple[PairedTaskDelta, ...]
    baseline_runs: tuple[TaskRunResult, ...]
    leviathan_runs: tuple[TaskRunResult, ...]
    improved_count: int
    regressed_count: int
    unchanged_count: int
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "deltas": [d.public_dict() for d in self.deltas],
            "improved_count": self.improved_count,
            "regressed_count": self.regressed_count,
            "unchanged_count": self.unchanged_count,
            "baseline_runs": [r.public_dict() for r in self.baseline_runs],
            "leviathan_runs": [r.public_dict() for r in self.leviathan_runs],
            "detail": self.detail,
            "truth": {
                "paired_same_tasks_same_budgets": True,
                "regressions_not_hidden_in_aggregate": True,
                "purpose_is_do_system_layers_improve_model": True,
            },
        }


def run_paired_evaluation(
    tasks: list[AssistantTask] | None = None,
    *,
    baseline_caller: Any | None = None,
    leviathan_caller: Any | None = None,
) -> PairedEvaluationReport:
    """Compare BASELINE (minimal tools) vs LEVIATHAN (full runtime helpers)."""
    catalog = tasks or default_assistant_tasks()
    baseline = AssistantBenchmarkRunner(model_caller=baseline_caller, profile="baseline")
    leviathan = AssistantBenchmarkRunner(model_caller=leviathan_caller, profile="leviathan")
    base_runs = tuple(baseline.run_suite(catalog))
    lev_runs = tuple(leviathan.run_suite(catalog))
    by_base = {r.task_id: r for r in base_runs}
    deltas: list[PairedTaskDelta] = []
    improved = regressed = unchanged = 0
    for lev in lev_runs:
        base = by_base[lev.task_id]
        imp = (not base.success) and lev.success
        reg = base.success and (not lev.success)
        if imp:
            improved += 1
        elif reg:
            regressed += 1
        else:
            unchanged += 1
        deltas.append(
            PairedTaskDelta(
                task_id=lev.task_id,
                family=lev.family,
                baseline_success=base.success,
                leviathan_success=lev.success,
                improved=imp,
                regressed=reg,
                baseline_metrics=base.metrics.public_dict(),
                leviathan_metrics=lev.metrics.public_dict(),
                detail=(
                    "improved"
                    if imp
                    else ("regressed" if reg else ("both_ok" if lev.success else "both_fail"))
                ),
            )
        )
    return PairedEvaluationReport(
        report_id=f"paired_{uuid.uuid4().hex[:12]}",
        deltas=tuple(deltas),
        baseline_runs=base_runs,
        leviathan_runs=lev_runs,
        improved_count=improved,
        regressed_count=regressed,
        unchanged_count=unchanged,
        detail=(
            f"improved={improved} regressed={regressed} unchanged={unchanged} "
            "— per-task deltas retained (no single aggregate hide)"
        ),
    )
