from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

    def public_dict(self) -> dict[str, Any]:
        return {
            "engage": self.engage,
            "depth": self.depth,
            "reason": self.reason,
            "critic_rounds": self.critic_rounds,
            "use_memory_tiers": list(self.use_memory_tiers),
            "residual_required": self.residual_required,
            "truth": {
                "cortex_engagement_is_not_completion": True,
                "neural_signal_is_not_authority": True,
            },
        }


class CortexPlanner:
    """Decide lean vs complex neuro path from plan + flags. Deterministic MVP."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_depth: int = 2,
        max_critic_rounds: int = 2,
    ) -> None:
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if max_critic_rounds < 0:
            raise ValueError("max_critic_rounds must be >= 0")
        self.enabled = enabled
        self.max_depth = max_depth
        self.max_critic_rounds = max_critic_rounds

    def plan(
        self,
        reasoning: ReasoningPlan,
        *,
        residual_available: bool = False,
        memory_tiers_enabled: bool = False,
        process_critic_enabled: bool = False,
    ) -> CortexEngagement:
        if not self.enabled:
            return CortexEngagement(
                engage=False,
                depth=0,
                reason="neuro cortex feature flag OFF",
                critic_rounds=0,
                use_memory_tiers=(),
                residual_required=False,
            )

        complexity = (reasoning.complexity or "").lower()
        intent = (reasoning.intent or "").lower()
        complex = complexity in {"high", "complex", "hard"} or intent in {
            "research",
            "coding",
            "analysis",
            "multi_step",
        }

        if not complex:
            return CortexEngagement(
                engage=False,
                depth=0,
                reason=f"lean path for complexity={complexity!r} intent={intent!r}",
                critic_rounds=0,
                use_memory_tiers=(0,) if memory_tiers_enabled else (),
                residual_required=False,
            )

        depth = min(self.max_depth, 2 if residual_available else 1)
        critic_rounds = min(self.max_critic_rounds, 2 if process_critic_enabled else 0)
        tiers: tuple[int, ...] = ()
        if memory_tiers_enabled:
            tiers = (0, 1, 2) if reasoning.use_knowledge else (0, 1)

        return CortexEngagement(
            engage=True,
            depth=depth,
            reason="complex query — engage cortex + optional memory/critic",
            critic_rounds=critic_rounds,
            use_memory_tiers=tiers,
            residual_required=residual_available,
        )
