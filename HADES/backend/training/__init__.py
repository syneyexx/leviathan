"""HADES Adaptive Training Memory Engine (ATME).

Lightweight planning, hardware probing and execution-plan types live here and are
safe to import from the normal FastAPI process. Heavy streaming/runtime code that
requires PyTorch is imported only inside the isolated training worker.
"""

from __future__ import annotations

from training.execution_plan import (
    PLANNER_VERSION,
    MemoryStrategy,
    TrainingExecutionPlan,
    confidence_rank,
)
from training.failure_codes import TrainingFailureCode

__all__ = [
    "PLANNER_VERSION",
    "MemoryStrategy",
    "TrainingExecutionPlan",
    "TrainingFailureCode",
    "confidence_rank",
]
