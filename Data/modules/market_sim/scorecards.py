"""Agent scorecards + leaderboard penalty (P3B / G27)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentScorecard:
    agent_id: str
    role: str = ""
    trials: int = 0
    wins: int = 0
    losses: int = 0
    vetoes: int = 0
    causality_violations: int = 0
    risk_vetoes: int = 0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    penalty: float = 0.0
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "trials": self.trials,
            "wins": self.wins,
            "losses": self.losses,
            "vetoes": self.vetoes,
            "causality_violations": self.causality_violations,
            "risk_vetoes": self.risk_vetoes,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "penalty": self.penalty,
            "score": self.score,
            "metadata": dict(self.metadata),
            "truth": {
                "kernel_metrics_only": True,
                "penalty_for_violations": True,
            },
        }


def compute_penalty(
    *,
    causality_violations: int = 0,
    risk_vetoes: int = 0,
    max_drawdown: float = 0.0,
) -> float:
    """Leaderboard penalty — violations and drawdown hurt rank."""
    return (
        float(causality_violations) * 10.0
        + float(risk_vetoes) * 2.0
        + max(0.0, float(max_drawdown)) * 50.0
    )


def build_scorecard(
    *,
    agent_id: str,
    role: str = "",
    trials: int = 0,
    wins: int = 0,
    losses: int = 0,
    vetoes: int = 0,
    causality_violations: int = 0,
    risk_vetoes: int = 0,
    total_return: float = 0.0,
    max_drawdown: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> AgentScorecard:
    penalty = compute_penalty(
        causality_violations=causality_violations,
        risk_vetoes=risk_vetoes,
        max_drawdown=max_drawdown,
    )
    # Higher is better; penalty subtracts.
    score = float(total_return) * 100.0 + float(wins) - float(losses) - penalty
    return AgentScorecard(
        agent_id=agent_id,
        role=role,
        trials=trials,
        wins=wins,
        losses=losses,
        vetoes=vetoes,
        causality_violations=causality_violations,
        risk_vetoes=risk_vetoes,
        total_return=float(total_return),
        max_drawdown=float(max_drawdown),
        penalty=penalty,
        score=score,
        metadata=dict(metadata or {}),
    )


def rank_scorecards(cards: list[AgentScorecard]) -> list[dict[str, Any]]:
    ordered = sorted(cards, key=lambda c: c.score, reverse=True)
    out = []
    for i, card in enumerate(ordered, start=1):
        row = card.public_dict()
        row["rank"] = i
        out.append(row)
    return out
