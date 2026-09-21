from __future__ import annotations

from Data.modules.function_runtime.types import SideEffect

from .types import PolicyDecision

# Effects that may proceed without a human/system approval.
AUTO_ALLOWED_EFFECTS = frozenset({SideEffect.READ})


class PolicyEngine:
    """Decide whether a capability requires approval based on side effects."""

    def evaluate(self, side_effects: tuple[SideEffect, ...] | list[SideEffect]) -> PolicyDecision:
        effects = tuple(side_effects)
        auto = tuple(e.value for e in effects if e in AUTO_ALLOWED_EFFECTS)
        gated = tuple(e.value for e in effects if e not in AUTO_ALLOWED_EFFECTS)
        if not gated:
            return PolicyDecision(
                requires_approval=False,
                reason="all side effects are auto-allowed (READ)",
                auto_effects=auto,
                gated_effects=(),
            )
        return PolicyDecision(
            requires_approval=True,
            reason=f"gated side effects require approval: {list(gated)}",
            auto_effects=auto,
            gated_effects=gated,
        )
