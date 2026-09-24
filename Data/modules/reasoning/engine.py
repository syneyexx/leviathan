from __future__ import annotations

from dataclasses import asdict, dataclass

from .retrieval_policy import decide_retrieval


@dataclass(frozen=True)
class ReasoningPlan:
    intent: str
    complexity: str
    use_knowledge: bool
    steps: tuple[str, ...]
    use_deep_recall: bool = False
    use_atlas: bool = False
    economy: dict | None = None
    retrieval_reason: str = ""
    use_memory: bool = True
    policy_version: str = "retrieval_policy.v1"

    def public_summary(self) -> dict:
        """Return a compact execution summary, never hidden chain-of-thought."""
        return asdict(self)


class ReasoningEngine:
    """Deterministic planning + retrieval-need classification.

    Stable seam for later planner/router work without making model-generated
    hidden reasoning authoritative.
    """

    def analyze(
        self,
        message: str,
        has_knowledge: bool,
        *,
        deep_recall_enabled: bool = False,
        economy_allow_deep_recall: bool = False,
        memory_coverage: float = 1.0,
        retrieval_enabled: bool = True,
        retrieval_mode: str = "auto",
        memory_enabled: bool = True,
    ) -> ReasoningPlan:
        decision = decide_retrieval(
            message,
            has_knowledge=has_knowledge,
            retrieval_enabled=retrieval_enabled,
            retrieval_mode=retrieval_mode,
            deep_recall_enabled=deep_recall_enabled,
            economy_allow_deep_recall=economy_allow_deep_recall,
            memory_enabled=memory_enabled,
            memory_coverage=memory_coverage,
        )
        return ReasoningPlan(
            intent=decision.intent,
            complexity=decision.complexity,
            use_knowledge=decision.use_knowledge,
            steps=decision.steps,
            use_deep_recall=decision.use_deep_recall,
            use_atlas=decision.use_atlas,
            retrieval_reason=decision.reason,
            use_memory=decision.use_memory,
            policy_version=decision.policy_version,
        )
