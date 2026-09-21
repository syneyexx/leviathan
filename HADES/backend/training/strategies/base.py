"""Strategy protocol for ATME execution backends."""

from __future__ import annotations

from typing import Any, Protocol

from training.execution_plan import MemoryStrategy, TrainingExecutionPlan


class TrainingStrategy(Protocol):
    name: MemoryStrategy

    def apply_model_load_kwargs(self, plan: TrainingExecutionPlan, base_kwargs: dict[str, Any]) -> dict[str, Any]:
        ...

    def prepare_model(self, model: Any, plan: TrainingExecutionPlan) -> Any:
        ...


def strategy_from_plan(plan: TrainingExecutionPlan) -> MemoryStrategy:
    return plan.strategy
