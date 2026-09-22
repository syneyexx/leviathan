from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EconomyDecision:
    allow_deep_recall: bool
    max_depth: int
    max_relation_count: int
    deep_recall_budget: int
    explanation_burden: str  # low | normal | high
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "allow_deep_recall": self.allow_deep_recall,
            "max_depth": self.max_depth,
            "max_relation_count": self.max_relation_count,
            "deep_recall_budget": self.deep_recall_budget,
            "explanation_burden": self.explanation_burden,
            "reason": self.reason,
            "truth": {
                "depth_on_demand_not_by_default": True,
                "governor_is_not_authority": True,
            },
        }


class CognitiveEconomyGovernor:
    """Lightweight limits on depth, memory descent, Deep Recall, explanation burden."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        default_deep_recall_budget: int = 800,
        max_depth: int = 2,
        max_relation_count: int = 12,
    ) -> None:
        self.enabled = enabled
        self.default_deep_recall_budget = default_deep_recall_budget
        self.max_depth = max_depth
        self.max_relation_count = max_relation_count

    def decide(
        self,
        *,
        complexity: str = "low",
        intent: str = "conversation",
        memory_coverage: float = 1.0,
        residual_available: bool = False,
        deep_recall_enabled: bool = False,
        explicit_deep_recall: bool = False,
        working_memory_load: float = 0.0,
    ) -> EconomyDecision:
        if not self.enabled:
            return EconomyDecision(
                allow_deep_recall=deep_recall_enabled and explicit_deep_recall,
                max_depth=self.max_depth,
                max_relation_count=self.max_relation_count,
                deep_recall_budget=self.default_deep_recall_budget,
                explanation_burden="normal",
                reason="economy_governor_disabled_passthrough",
            )

        complexity_l = (complexity or "low").lower()
        intent_l = (intent or "conversation").lower()
        needs_depth = complexity_l in {"medium", "high", "complex"} or intent_l in {
            "research",
            "analysis",
            "knowledge",
            "coding",
        }
        coverage_gap = memory_coverage < 0.35
        allow = bool(
            deep_recall_enabled
            and (explicit_deep_recall or (needs_depth and coverage_gap) or working_memory_load >= 0.85)
        )

        depth = 0
        if needs_depth:
            depth = 1
        if allow or residual_available:
            depth = min(self.max_depth, 2)
        if complexity_l == "low" and not explicit_deep_recall:
            depth = 0

        burden = "low"
        if needs_depth:
            burden = "normal"
        if allow and complexity_l == "high":
            burden = "high"

        budget = self.default_deep_recall_budget
        if burden == "high":
            budget = int(self.default_deep_recall_budget * 1.5)
        if burden == "low":
            budget = int(self.default_deep_recall_budget * 0.5)

        reason = (
            f"depth_on_demand complexity={complexity_l} intent={intent_l} "
            f"coverage={memory_coverage:.2f} allow_deep_recall={allow}"
        )
        return EconomyDecision(
            allow_deep_recall=allow,
            max_depth=depth,
            max_relation_count=self.max_relation_count if needs_depth else min(4, self.max_relation_count),
            deep_recall_budget=budget,
            explanation_burden=burden,
            reason=reason,
        )
