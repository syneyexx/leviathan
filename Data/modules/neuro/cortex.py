from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from Data.modules.reasoning import ReasoningPlan


@dataclass(frozen=True)
class CortexEngagement:
    """Advisory plan for dynamic depth — not completion authority."""

    engage: bool
    depth: int
    reason: str
    critic_rounds: int
    use_memory_tiers: tuple[int, ...]
    residual_required: bool
    path: str = "lean"  # lean | complex
    token_budget: int | None = None
    memory_coverage: float = 0.0
    working_memory_load: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "engage": self.engage,
            "depth": self.depth,
            "reason": self.reason,
            "critic_rounds": self.critic_rounds,
            "use_memory_tiers": list(self.use_memory_tiers),
            "residual_required": self.residual_required,
            "path": self.path,
            "token_budget": self.token_budget,
            "memory_coverage": self.memory_coverage,
            "working_memory_load": self.working_memory_load,
            "truth": {
                "cortex_engagement_is_not_completion": True,
                "neural_signal_is_not_authority": True,
                "depth_is_not_authority": True,
            },
        }


class CortexPlanner:
    """Decide lean vs complex neuro path from plan + residual/memory/budget signals."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_depth: int = 2,
        max_critic_rounds: int = 2,
        default_token_budget: int = 6000,
    ) -> None:
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if max_critic_rounds < 0:
            raise ValueError("max_critic_rounds must be >= 0")
        self.enabled = enabled
        self.max_depth = max_depth
        self.max_critic_rounds = max_critic_rounds
        self.default_token_budget = default_token_budget

    def plan(
        self,
        reasoning: ReasoningPlan,
        *,
        residual_available: bool = False,
        memory_tiers_enabled: bool = False,
        process_critic_enabled: bool = False,
        token_budget: int | None = None,
        memory_hit_quality: float = 0.0,
        memory_coverage: float = 0.0,
        working_memory_load: float = 0.0,
    ) -> CortexEngagement:
        budget = token_budget if token_budget is not None else self.default_token_budget
        if not self.enabled:
            return CortexEngagement(
                engage=False,
                depth=0,
                reason="neuro cortex feature flag OFF",
                critic_rounds=0,
                use_memory_tiers=(),
                residual_required=False,
                path="lean",
                token_budget=budget,
                memory_coverage=memory_coverage,
                working_memory_load=working_memory_load,
            )

        complexity = (reasoning.complexity or "").lower()
        intent = (reasoning.intent or "").lower()
        complex = complexity in {"high", "complex", "hard"} or intent in {
            "research",
            "coding",
            "analysis",
            "multi_step",
        }
        # Elevate to complex when memory coverage is poor on knowledge intents.
        if intent in {"knowledge", "research", "analysis"} and memory_coverage < 0.25:
            complex = True
        # Elevate when working memory is saturated — need deeper retrieve/critic.
        if working_memory_load >= 0.85 and complexity in {"medium", "high"}:
            complex = True

        if not complex:
            return CortexEngagement(
                engage=False,
                depth=0,
                reason=f"lean path for complexity={complexity!r} intent={intent!r}",
                critic_rounds=0,
                use_memory_tiers=(0,) if memory_tiers_enabled else (),
                residual_required=False,
                path="lean",
                token_budget=budget,
                memory_coverage=memory_coverage,
                working_memory_load=working_memory_load,
            )

        # Depth scales with residual availability, budget headroom, and memory quality.
        depth = 1
        if residual_available:
            depth = 2
        if budget >= 8000 and residual_available:
            depth = min(self.max_depth, max(depth, 2))
        if memory_hit_quality < 0.35 and self.max_depth >= 2:
            depth = min(self.max_depth, max(depth, 2))
        depth = min(self.max_depth, depth)

        critic_rounds = 0
        if process_critic_enabled:
            critic_rounds = 1
            if complexity == "high" or memory_coverage < 0.4:
                critic_rounds = min(self.max_critic_rounds, 2)
            if residual_available and budget >= 4000:
                critic_rounds = min(self.max_critic_rounds, max(critic_rounds, 2))

        tiers: tuple[int, ...] = ()
        if memory_tiers_enabled:
            if reasoning.use_knowledge or intent in {"research", "knowledge", "analysis"}:
                tiers = (0, 1, 2)
            else:
                tiers = (0, 1)
            if memory_coverage >= 0.8 and working_memory_load < 0.5:
                # High coverage — still consult Tier0/1; Tier2 optional.
                tiers = (0, 1, 2) if reasoning.use_knowledge else (0, 1)

        return CortexEngagement(
            engage=True,
            depth=depth,
            reason=(
                "complex path — cortex + memory/critic "
                f"(residual={residual_available}, coverage={memory_coverage:.2f}, "
                f"wm_load={working_memory_load:.2f}, budget={budget})"
            ),
            critic_rounds=critic_rounds,
            use_memory_tiers=tiers,
            residual_required=residual_available,
            path="complex",
            token_budget=budget,
            memory_coverage=memory_coverage,
            working_memory_load=working_memory_load,
        )
