"""Bounded ATME auto-tuning (Phase 7) — disabled unless explicitly enabled.

Never silently changes semantic training intent, dataset mapping, or learning
objective. Candidates require a bounded warm-up and safety abort.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from training.execution_plan import TrainingExecutionPlan


@dataclass(frozen=True)
class TuneCandidate:
    batch_size: int | None = None
    gradient_accumulation_steps: int | None = None
    activation_checkpointing: str | None = None
    buffer_count: int | None = None
    reason: str = ""


def propose_safe_candidates(
    plan: TrainingExecutionPlan,
    *,
    enabled: bool = False,
    max_candidates: int = 3,
) -> list[TuneCandidate]:
    """Return optional micro-tune candidates only when explicitly enabled."""

    if not enabled:
        return []
    candidates: list[TuneCandidate] = []
    if plan.strategy.value.endswith("streaming") and plan.buffer_count < 2:
        candidates.append(
            TuneCandidate(buffer_count=2, reason="try double-buffer after single-buffer parity")
        )
    if plan.activation_checkpointing == "auto":
        candidates.append(
            TuneCandidate(activation_checkpointing="enabled", reason="reduce activation pressure")
        )
    return candidates[: max(0, int(max_candidates))]


def apply_candidate_to_parameters(params: dict[str, Any], candidate: TuneCandidate) -> dict[str, Any]:
    updated = dict(params)
    if candidate.batch_size is not None:
        updated["batch_size"] = int(candidate.batch_size)
    if candidate.gradient_accumulation_steps is not None:
        updated["gradient_accumulation_steps"] = int(candidate.gradient_accumulation_steps)
    if candidate.activation_checkpointing is not None:
        updated["activation_checkpointing"] = candidate.activation_checkpointing
    if candidate.buffer_count is not None:
        updated["resolved_buffer_count"] = int(candidate.buffer_count)
    return updated
