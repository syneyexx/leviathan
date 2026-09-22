from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from .residual import ResidualTensorRef
from .types import NeuroSignal


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

    Grounding heavily prefers Evidence IDs and Knowledge document/chunk IDs.
    Without citations, factual_grounding drops hard. Advisory only.
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

        risk_tokens = ("delete", "rm -rf", "overwrite", "force", "ignore policy")
        risk_hits = sum(1 for token in risk_tokens if token in lowered)
        consistency = max(0.0, min(1.0, 0.85 - 0.2 * risk_hits + 0.1 * unique))

        steps = list(plan_steps or ())
        if not steps:
            goal_progress = 0.4
        else:
            covered = sum(
                1
                for step in steps
                if step.lower() in lowered
                or any(w in lowered for w in step.lower().split("_") if len(w) > 2)
            )
            goal_progress = round(covered / max(len(steps), 1), 3)

        evidence_pool = [str(x) for x in (evidence_ids or ()) if str(x).strip()]
        knowledge_pool = [str(x) for x in (knowledge_ids or ()) if str(x).strip()]
        notes: list[str] = []

        if evidence_pool or knowledge_pool:
            # Evidence citations weigh more heavily than knowledge ids.
            evidence_cited = sum(1 for item in evidence_pool if item.lower() in lowered)
            knowledge_cited = sum(1 for item in knowledge_pool if item.lower() in lowered)
            evidence_ratio = evidence_cited / max(len(evidence_pool), 1) if evidence_pool else 0.0
            knowledge_ratio = knowledge_cited / max(len(knowledge_pool), 1) if knowledge_pool else 0.0
            factual_grounding = round(
                min(1.0, 0.15 + 0.55 * evidence_ratio + 0.30 * knowledge_ratio),
                3,
            )
            if evidence_cited == 0 and knowledge_cited == 0:
                # Hard drop when IDs were available but none cited.
                factual_grounding = 0.08
                notes.append("ids_available_but_uncited — grounding collapsed")
                method = "lexical_grounding_ids_missed"
            else:
                method = "lexical_grounding_ids"
                notes.append(
                    f"evidence_cited={evidence_cited}/{len(evidence_pool)}; "
                    f"knowledge_cited={knowledge_cited}/{len(knowledge_pool)}"
                )
        else:
            # No Evidence/Knowledge IDs in context — ungrounded heuristic, capped low.
            citation_like = bool(re.search(r"\b(evid|doc|chunk|source)[-_]?[a-z0-9]+\b", lowered))
            factual_grounding = 0.18 if citation_like else 0.05
            method = "lexical_ungrounded_heuristic"
            notes.append("no evidence/knowledge ids — grounding capped low")

        notes.append("heuristic critic — residual tensors not required for this path")
        return CriticScore(
            consistency=round(consistency, 3),
            goal_progress=goal_progress,
            factual_grounding=factual_grounding,
            method=method,
            notes=tuple(notes),
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
                factual_grounding=0.05 if not (knowledge_ids or evidence_ids) else 0.15,
                method="residual_unavailable",
                notes=(tensor.note or "residual tensor unavailable",),
            )
        meta = tensor.metadata or {}
        norm = float(meta.get("norm") or 0.0)
        consistency = max(0.0, min(1.0, 1.0 - abs(norm - 1.0) / 5.0))
        if plan_steps:
            goal_progress = 0.55
        else:
            goal_progress = 0.4
        if evidence_ids:
            factual_grounding = 0.62
            method = "residual_stats_with_evidence_context"
        elif knowledge_ids:
            factual_grounding = 0.48
            method = "residual_stats_with_knowledge_context"
        else:
            factual_grounding = 0.12
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
            strength=max(0.0, min(1.0, score.aggregate)),
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
