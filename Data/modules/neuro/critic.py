from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from .types import NeuroSignal
from .residual import ResidualTensorRef


@dataclass(frozen=True)
class CriticScore:
    consistency: float
    goal_progress: float
    factual_grounding: float
    method: str
    notes: tuple[str, ...] = ()

    @property
    def aggregate(self) -> float:
        return round((self.consistency + self.goal_progress + self.factual_grounding) / 3.0, 3)

    def public_dict(self) -> dict[str, Any]:
        return {
            "consistency": self.consistency,
            "goal_progress": self.goal_progress,
            "factual_grounding": self.factual_grounding,
            "aggregate": self.aggregate,
            "method": self.method,
            "notes": list(self.notes),
            "truth": {
                "critic_is_advisory": True,
                "neural_signal_is_not_authority": True,
            },
        }


class ProcessCritic:
    """Scores intermediate reasoning for consistency / progress / grounding.

    Without residual tensors, uses lexical heuristics with honest provenance.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    def score(
        self,
        text: str,
        *,
        plan_steps: Sequence[str] | None = None,
        knowledge_ids: Sequence[str] | None = None,
        evidence_ids: Sequence[str] | None = None,
    ) -> CriticScore:
        if not self.enabled:
            return CriticScore(
                consistency=0.0,
                goal_progress=0.0,
                factual_grounding=0.0,
                method="disabled",
                notes=("process critic feature flag OFF",),
            )

        lowered = text.lower()
        words = re.findall(r"[a-z0-9]{3,}", lowered)
        unique = len(set(words)) / max(len(words), 1)

        # Consistency: penalize high-risk destructive phrasing without evidence ids.
        risk_tokens = ("delete", "rm -rf", "overwrite", "force", "ignore policy")
        risk_hits = sum(1 for token in risk_tokens if token in lowered)
        consistency = max(0.0, min(1.0, 0.85 - 0.2 * risk_hits + 0.1 * unique))

        steps = list(plan_steps or ())
        if not steps:
            goal_progress = 0.4
        else:
            covered = sum(1 for step in steps if step.lower() in lowered or any(w in lowered for w in step.lower().split("_")))
            goal_progress = round(covered / max(len(steps), 1), 3)

        grounded_pool = list(knowledge_ids or []) + list(evidence_ids or [])
        if grounded_pool:
            cited = sum(1 for item in grounded_pool if item.lower() in lowered)
            factual_grounding = round(min(1.0, cited / max(len(grounded_pool), 1) + 0.2), 3)
            method = "lexical_grounding_ids"
        else:
            factual_grounding = 0.25
            method = "lexical_ungrounded_heuristic"

        return CriticScore(
            consistency=round(consistency, 3),
            goal_progress=goal_progress,
            factual_grounding=factual_grounding,
            method=method,
            notes=("heuristic critic — residual tensors not required for this path",),
        )

    def score_residual(
        self,
        tensor: ResidualTensorRef,
        *,
        plan_steps: Sequence[str] | None = None,
        knowledge_ids: Sequence[str] | None = None,
        evidence_ids: Sequence[str] | None = None,
    ) -> CriticScore:
        """Score using residual tensor availability/stats when present."""
        if not self.enabled:
            return CriticScore(
                consistency=0.0,
                goal_progress=0.0,
                factual_grounding=0.0,
                method="disabled",
                notes=("process critic feature flag OFF",),
            )
        if not tensor.available:
            return CriticScore(
                consistency=0.3,
                goal_progress=0.3,
                factual_grounding=0.2,
                method="residual_unavailable",
                notes=(tensor.note or "residual tensor unavailable",),
            )
        meta = tensor.metadata or {}
        norm = float(meta.get("norm") or 0.0)
        # Bounded heuristic on residual energy — advisory only.
        consistency = max(0.0, min(1.0, 1.0 - abs(norm - 1.0) / 5.0))
        goal_progress = 0.5 if plan_steps else 0.4
        if knowledge_ids or evidence_ids:
            factual_grounding = 0.55
            method = "residual_stats_with_id_context"
        else:
            factual_grounding = 0.35
            method = "residual_stats_ungrounded"
        return CriticScore(
            consistency=round(consistency, 3),
            goal_progress=goal_progress,
            factual_grounding=factual_grounding,
            method=method,
            notes=(f"hook={tensor.hook.name}", "critic_on_residual advisory"),
        )

    def as_signal(self, score: CriticScore) -> NeuroSignal:
        return NeuroSignal(
            signal_id=str(uuid.uuid4()),
            kind="process_critic",
            strength=score.aggregate,
            summary=(
                f"Critic aggregate={score.aggregate} "
                f"(consistency={score.consistency}, progress={score.goal_progress}, "
                f"grounding={score.factual_grounding})"
            ),
            provenance={
                "method": score.method,
                "scores": score.public_dict(),
                "advisory_only": True,
            },
        )
