"""Institutional agent team binding (W23)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


REQUIRED_TEAM_ROLES = (
    "strategy_researcher",
    "critic",
    "risk",
    "execution",
    "postmortem",
)


@dataclass
class TeamRoleBinding:
    role: str
    agent_id: str
    budget_pct: float = 0.0
    can_veto: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "agentId": self.agent_id,
            "budgetPct": self.budget_pct,
            "canVeto": self.can_veto,
        }


@dataclass
class InstitutionalAgentTeam:
    team_id: str
    bindings: list[TeamRoleBinding] = field(default_factory=list)
    evidence_contract: str = "trial_ledger_required"

    def bind(self, role: str, agent_id: str, *, budget_pct: float = 0.0, can_veto: bool = False) -> TeamRoleBinding:
        binding = TeamRoleBinding(role=role, agent_id=agent_id, budget_pct=budget_pct, can_veto=can_veto)
        self.bindings = [b for b in self.bindings if b.role != role]
        self.bindings.append(binding)
        return binding

    def missing_roles(self) -> list[str]:
        present = {b.role for b in self.bindings}
        return [r for r in REQUIRED_TEAM_ROLES if r not in present]

    def risk_can_veto(self) -> bool:
        return any(b.role == "risk" and b.can_veto for b in self.bindings)

    def public_dict(self) -> dict[str, Any]:
        return {
            "teamId": self.team_id,
            "bindings": [b.public_dict() for b in self.bindings],
            "missingRoles": self.missing_roles(),
            "riskCanVeto": self.risk_can_veto(),
            "evidenceContract": self.evidence_contract,
            "complete": not self.missing_roles() and self.risk_can_veto(),
            "truth": {
                "risk_veto_required_for_institutional_team": True,
                "live_trading_blocked": True,
            },
        }
