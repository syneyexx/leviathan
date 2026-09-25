"""Canonical RewardSpec for TradingGym (P1C).

Rewards are kernel-derived from equity / fills — never from frontend, LLM, or
agent claims. Unknown definitions remain UNMEASURED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


class RewardDefinition:
    EQUITY_DELTA = "equity_delta"
    LOG_RETURN = "log_return"
    REALIZED_PNL_DELTA = "realized_pnl_delta"
    # Sparse terminal — measured only at episode end
    EPISODE_TOTAL_RETURN = "episode_total_return"


@dataclass(frozen=True)
class RewardSpec:
    """Immutable reward contract bound into RunInputFingerprint."""

    definition: str = RewardDefinition.EQUITY_DELTA
    scale: float = 1.0
    clip: float | None = None
    include_unrealized: bool = True
    version: str = "reward_spec-1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition,
            "scale": self.scale,
            "clip": self.clip,
            "include_unrealized": self.include_unrealized,
            "version": self.version,
            "metadata": dict(self.metadata),
            "truth": {
                "kernel_derived": True,
                "never_from_frontend_or_llm": True,
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RewardSpec":
        raw = dict(raw or {})
        return cls(
            definition=str(raw.get("definition") or RewardDefinition.EQUITY_DELTA),
            scale=float(raw.get("scale") if raw.get("scale") is not None else 1.0),
            clip=float(raw["clip"]) if raw.get("clip") is not None else None,
            include_unrealized=bool(raw.get("include_unrealized", True)),
            version=str(raw.get("version") or "reward_spec-1"),
            metadata=dict(raw.get("metadata") or {}),
        )


def compute_step_reward(
    spec: RewardSpec,
    *,
    prev_equity: float | None,
    equity: float | None,
    prev_realized_pnl: float | None = None,
    realized_pnl: float | None = None,
    done: bool = False,
    initial_cash: float | None = None,
) -> dict[str, Any]:
    """Compute one step reward from measured ledger state."""
    definition = spec.definition
    base: dict[str, Any] = {
        "definition": definition,
        "reward_spec_version": spec.version,
        "status": "UNMEASURED",
        "value": None,
    }
    value: float | None = None

    if definition == RewardDefinition.EQUITY_DELTA:
        if prev_equity is None or equity is None:
            return base
        value = float(equity) - float(prev_equity)
    elif definition == RewardDefinition.LOG_RETURN:
        if prev_equity is None or equity is None or float(prev_equity) <= 0:
            return base
        import math

        value = math.log(max(float(equity), 1e-12) / float(prev_equity))
    elif definition == RewardDefinition.REALIZED_PNL_DELTA:
        if prev_realized_pnl is None or realized_pnl is None:
            return base
        value = float(realized_pnl) - float(prev_realized_pnl)
    elif definition == RewardDefinition.EPISODE_TOTAL_RETURN:
        if not done:
            return {
                **base,
                "status": "UNMEASURED",
                "note": "sparse terminal reward; measured only when done=True",
            }
        if initial_cash is None or equity is None or float(initial_cash) == 0:
            return base
        value = (float(equity) - float(initial_cash)) / float(initial_cash)
    else:
        return {
            **base,
            "status": "UNMEASURED",
            "note": f"unknown reward definition {definition!r}",
        }

    value = float(value) * float(spec.scale)
    if spec.clip is not None:
        c = abs(float(spec.clip))
        value = max(-c, min(c, value))
    return {
        "definition": definition,
        "reward_spec_version": spec.version,
        "status": "MEASURED",
        "value": value,
        "truth": {"kernel_derived": True},
    }


def validate_reward_spec(spec: RewardSpec) -> tuple[bool, str]:
    known = {
        RewardDefinition.EQUITY_DELTA,
        RewardDefinition.LOG_RETURN,
        RewardDefinition.REALIZED_PNL_DELTA,
        RewardDefinition.EPISODE_TOTAL_RETURN,
    }
    if spec.definition not in known:
        return False, f"unknown definition {spec.definition}"
    if spec.scale == 0:
        return False, "scale must be non-zero"
    return True, "ok"
