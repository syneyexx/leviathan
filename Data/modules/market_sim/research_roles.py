"""Canonical research responsibilities — reconcile role vocabularies without a second fleet.

Sources audited (do not duplicate as parallel fleets):
- roles.TRADING_ROLE_SPECS / ensure_trading_agents_in_fleet
- agent_lab.LabRole
- orchestra.types.TRADING_ROLES + orchestra.executors.ROLE_ALIASES
- institutional_team.REQUIRED_TEAM_ROLES
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .roles import TRADING_ROLE_SPECS, ensure_trading_agents_in_fleet


class ResearchResponsibility(str, Enum):
    """Canonical research-lab responsibilities (not a new fleet kind)."""

    MARKET_REGIME_ANALYST = "MARKET_REGIME_ANALYST"
    STRATEGY_RESEARCHER = "STRATEGY_RESEARCHER"
    STRATEGY_AUTHOR = "STRATEGY_AUTHOR"
    CRITIC = "CRITIC"
    BACKTESTER = "BACKTESTER"
    EVALUATOR = "EVALUATOR"
    RISK_OFFICER = "RISK_OFFICER"
    POSTMORTEM_LIBRARIAN = "POSTMORTEM_LIBRARIAN"
    ORCHESTRATOR = "ORCHESTRATOR"


@dataclass(frozen=True)
class ResearchRoleDescriptor:
    """Maps one canonical responsibility onto existing fleet / lab / orchestra strings."""

    responsibility: ResearchResponsibility
    fleet_role: str
    label: str
    description: str
    aliases: tuple[str, ...] = ()
    lab_roles: tuple[str, ...] = ()
    orchestra_roles: tuple[str, ...] = ()
    institutional_roles: tuple[str, ...] = ()
    perception_cycle_rank: int = 0
    may_propose: bool = False
    may_veto: bool = False
    output_contract: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "responsibility": self.responsibility.value,
            "fleet_role": self.fleet_role,
            "label": self.label,
            "description": self.description,
            "aliases": list(self.aliases),
            "lab_roles": list(self.lab_roles),
            "orchestra_roles": list(self.orchestra_roles),
            "institutional_roles": list(self.institutional_roles),
            "perception_cycle_rank": self.perception_cycle_rank,
            "may_propose": self.may_propose,
            "may_veto": self.may_veto,
            "output_contract": list(self.output_contract),
            "tags": list(self.tags),
            "truth": {
                "no_second_fleet": True,
                "registers_via_ensure_trading_agents_in_fleet": True,
            },
        }


def _desc(
    responsibility: ResearchResponsibility,
    *,
    fleet_role: str,
    label: str,
    description: str,
    perception_cycle_rank: int,
    aliases: tuple[str, ...] = (),
    lab_roles: tuple[str, ...] = (),
    orchestra_roles: tuple[str, ...] = (),
    institutional_roles: tuple[str, ...] = (),
    may_propose: bool = False,
    may_veto: bool = False,
    output_contract: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
) -> ResearchRoleDescriptor:
    return ResearchRoleDescriptor(
        responsibility=responsibility,
        fleet_role=fleet_role,
        label=label,
        description=description,
        aliases=aliases,
        lab_roles=lab_roles,
        orchestra_roles=orchestra_roles,
        institutional_roles=institutional_roles,
        perception_cycle_rank=perception_cycle_rank,
        may_propose=may_propose,
        may_veto=may_veto,
        output_contract=output_contract,
        tags=tags,
    )


CANONICAL_RESEARCH_ROLES: dict[str, ResearchRoleDescriptor] = {
    ResearchResponsibility.MARKET_REGIME_ANALYST.value: _desc(
        ResearchResponsibility.MARKET_REGIME_ANALYST,
        fleet_role="market_analyst",
        label="Market Regime Analyst",
        description="Perception: causal market/regime state; proposes regime hypotheses.",
        perception_cycle_rank=10,
        aliases=("market_analyst", "macro_regime_analyst", "signal_analyst"),
        orchestra_roles=("market_analyst", "macro_regime_analyst", "signal_analyst"),
        may_propose=True,
        output_contract=("hypothesis", "rationale", "features", "regime"),
        tags=("trading", "market_sim", "perception"),
    ),
    ResearchResponsibility.STRATEGY_RESEARCHER.value: _desc(
        ResearchResponsibility.STRATEGY_RESEARCHER,
        fleet_role="strategy_researcher",
        label="Strategy Researcher",
        description="Designs/refines strategy hypotheses within validated DSL families.",
        perception_cycle_rank=20,
        aliases=("strategy_researcher", "quant_researcher"),
        lab_roles=("quant_researcher",),
        orchestra_roles=("strategy_researcher",),
        institutional_roles=("strategy_researcher",),
        may_propose=True,
        output_contract=("strategy_patch", "hypothesis", "rationale"),
        tags=("trading", "market_sim", "research"),
    ),
    ResearchResponsibility.STRATEGY_AUTHOR.value: _desc(
        ResearchResponsibility.STRATEGY_AUTHOR,
        fleet_role="strategy_author",
        label="Strategy Author",
        description="Emits bounded Strategy DSL specs (no arbitrary Python).",
        perception_cycle_rank=40,
        aliases=("strategy_author", "strategy_architect"),
        lab_roles=("strategy_architect",),
        orchestra_roles=("strategy_author",),
        may_propose=True,
        output_contract=("entry_rules", "exit_rules", "parameters", "family"),
        tags=("trading", "market_sim", "authoring"),
    ),
    ResearchResponsibility.CRITIC.value: _desc(
        ResearchResponsibility.CRITIC,
        fleet_role="critic",
        label="Strategy Critic",
        description="Falsification pressure and counter-arguments on proposals.",
        perception_cycle_rank=30,
        aliases=("critic",),
        lab_roles=("critic",),
        orchestra_roles=("critic",),
        institutional_roles=("critic",),
        may_veto=True,
        output_contract=("counterargument", "risk_flag", "verdict"),
        tags=("trading", "market_sim", "critique"),
    ),
    ResearchResponsibility.BACKTESTER.value: _desc(
        ResearchResponsibility.BACKTESTER,
        # No dedicated fleet backtester row — measurement is owned by evaluator path.
        fleet_role="evaluator",
        label="Backtester",
        description="Runs historical trials; maps onto fleet evaluator for registration.",
        perception_cycle_rank=50,
        aliases=("backtester",),
        lab_roles=("backtester",),
        orchestra_roles=("evaluator",),
        may_propose=False,
        output_contract=("metrics", "trial_refs"),
        tags=("trading", "market_sim", "backtest"),
    ),
    ResearchResponsibility.EVALUATOR.value: _desc(
        ResearchResponsibility.EVALUATOR,
        fleet_role="evaluator",
        label="Independent Evaluator",
        description="Out-of-sample evaluation; does not trade during design window.",
        perception_cycle_rank=60,
        aliases=("evaluator",),
        orchestra_roles=("evaluator",),
        may_propose=False,
        output_contract=("metrics", "accept_or_reject", "error_analysis"),
        tags=("trading", "market_sim", "evaluation"),
    ),
    ResearchResponsibility.RISK_OFFICER.value: _desc(
        ResearchResponsibility.RISK_OFFICER,
        fleet_role="risk_agent",
        label="Risk Officer",
        description="Hard veto on orders; cannot be bypassed by model output.",
        perception_cycle_rank=70,
        aliases=("risk_agent", "risk_officer", "risk"),
        lab_roles=("risk_officer",),
        orchestra_roles=("risk_officer", "risk_agent"),
        institutional_roles=("risk",),
        may_veto=True,
        output_contract=("veto", "limit_check"),
        tags=("trading", "market_sim", "risk"),
    ),
    ResearchResponsibility.POSTMORTEM_LIBRARIAN.value: _desc(
        ResearchResponsibility.POSTMORTEM_LIBRARIAN,
        fleet_role="postmortem_agent",
        label="Postmortem Librarian",
        description="Writes lessons from decision records; curates StrategyMemory.",
        perception_cycle_rank=80,
        aliases=("postmortem_agent", "librarian_postmortem", "postmortem", "librarian"),
        lab_roles=("librarian_postmortem",),
        orchestra_roles=("postmortem_agent",),
        institutional_roles=("postmortem",),
        may_propose=True,
        output_contract=("claim", "evidenceRefs", "confidence"),
        tags=("trading", "market_sim", "learning"),
    ),
    ResearchResponsibility.ORCHESTRATOR.value: _desc(
        ResearchResponsibility.ORCHESTRATOR,
        fleet_role="trading_orchestrator",
        label="Research Orchestrator",
        description="Owns research task status, deadlines, iteration caps, stop criteria.",
        perception_cycle_rank=90,
        aliases=("trading_orchestrator", "trade_orchestra", "orchestrator"),
        orchestra_roles=("trading_orchestrator", "trade_orchestra"),
        may_propose=False,
        output_contract=("task_status", "stop_decision", "assignment"),
        tags=("trading", "market_sim", "orchestrator"),
    ),
}


# Alias → canonical responsibility key (uppercase enum value)
_ALIAS_TO_RESPONSIBILITY: dict[str, str] = {}
for _key, _desc_obj in CANONICAL_RESEARCH_ROLES.items():
    _ALIAS_TO_RESPONSIBILITY[_key.lower()] = _key
    _ALIAS_TO_RESPONSIBILITY[_desc_obj.fleet_role.lower()] = _key
    for _alias in (
        _desc_obj.aliases
        + _desc_obj.lab_roles
        + _desc_obj.orchestra_roles
        + _desc_obj.institutional_roles
    ):
        _ALIAS_TO_RESPONSIBILITY[str(_alias).lower()] = _key


# Strategy author is in orchestra TRADING_ROLES but not TRADING_ROLE_SPECS.
# Registration still goes through ensure_trading_agents_in_fleet for fleet rows;
# resolve_fleet_role returns the orchestra string for authoring prompts.
_STRATEGY_AUTHOR_FLEET_FALLBACK = "strategy_researcher"


def resolve_fleet_role(responsibility: str) -> str:
    """Map a responsibility / alias string onto the fleet role key used for prompts."""
    raw = str(responsibility or "").strip()
    if not raw:
        raise ValueError("responsibility is required")
    key = _ALIAS_TO_RESPONSIBILITY.get(raw.lower()) or _ALIAS_TO_RESPONSIBILITY.get(raw.upper())
    if key is None:
        # Pass-through known TRADING_ROLE_SPECS roles
        known = {s["role"] for s in TRADING_ROLE_SPECS}
        if raw in known:
            return raw
        raise ValueError(f"unknown research responsibility: {responsibility!r}")
    return CANONICAL_RESEARCH_ROLES[key].fleet_role


def research_role_order() -> list[str]:
    """Perception → authoring → evaluation cycle order (canonical responsibility keys)."""
    ordered = sorted(
        CANONICAL_RESEARCH_ROLES.values(),
        key=lambda d: (d.perception_cycle_rank, d.responsibility.value),
    )
    return [d.responsibility.value for d in ordered]


def get_research_role(responsibility: str) -> ResearchRoleDescriptor:
    raw = str(responsibility or "").strip()
    key = _ALIAS_TO_RESPONSIBILITY.get(raw.lower()) or _ALIAS_TO_RESPONSIBILITY.get(raw.upper())
    if key is None:
        raise ValueError(f"unknown research responsibility: {responsibility!r}")
    return CANONICAL_RESEARCH_ROLES[key]


def ensure_research_agents_registered(fleet: Any) -> list[str]:
    """Idempotently ensure trading research roles exist on the existing Agent Fleet.

    Reuses ``ensure_trading_agents_in_fleet`` — does not create a second fleet.
    Returns fleet role keys relevant to the research cycle (including aliases
    that resolve onto those rows).
    """
    ensure_trading_agents_in_fleet(fleet)
    # Prefer fleet rows that actually exist in TRADING_ROLE_SPECS; strategy_author
    # resolves to its own orchestra string for prompts but registers via researcher.
    research_fleet_roles: list[str] = []
    seen: set[str] = set()
    for resp_key in research_role_order():
        desc = CANONICAL_RESEARCH_ROLES[resp_key]
        role = desc.fleet_role
        # strategy_author is orchestra-native; ensure a fleet-backed fallback is listed
        if role == "strategy_author":
            role = _STRATEGY_AUTHOR_FLEET_FALLBACK
            if "strategy_author" not in seen:
                research_fleet_roles.append("strategy_author")
                seen.add("strategy_author")
        if role not in seen:
            research_fleet_roles.append(role)
            seen.add(role)
    return research_fleet_roles


__all__ = [
    "CANONICAL_RESEARCH_ROLES",
    "ResearchResponsibility",
    "ResearchRoleDescriptor",
    "ensure_research_agents_registered",
    "get_research_role",
    "research_role_order",
    "resolve_fleet_role",
]
