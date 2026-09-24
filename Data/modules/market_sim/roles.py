"""Trading agent roles — register into existing Agent Fleet (no second fleet)."""

from __future__ import annotations

from typing import Any

from .types import AgentRole


# Extended roles for trading research (stored as role strings on fleet agents)
TRADING_ROLE_SPECS: list[dict[str, Any]] = [
    {
        "key": "market_analyst",
        "name": "Market Analyst",
        "kind": "specialist",
        "role": "market_analyst",
        "tags": ["trading", "market_sim"],
        "description": "Analyzes causal market state; proposes regime hypotheses.",
        "capabilities": ["market_sim.observe", "market_sim.propose"],
        "authority": {"may_propose": True, "may_order": True, "may_veto": False},
        "output_contract": ["hypothesis", "rationale", "features"],
        "budget": {"max_model_calls": 8, "max_tokens": 4000},
    },
    {
        "key": "strategy_researcher",
        "name": "Strategy Researcher",
        "kind": "research",
        "role": "strategy_researcher",
        "tags": ["trading", "market_sim"],
        "description": "Designs/selects DSL strategy versions within validated schema.",
        "capabilities": ["market_sim.strategy", "market_sim.propose"],
        "authority": {"may_propose": True, "may_order": True, "may_veto": False},
        "output_contract": ["strategy_patch", "hypothesis", "rationale"],
        "budget": {"max_model_calls": 10, "max_tokens": 6000, "max_param_trials": 12},
    },
    {
        "key": "critic",
        "name": "Strategy Critic",
        "kind": "specialist",
        "role": "critic",
        "tags": ["trading", "market_sim"],
        "description": "Counter-arguments and falsification pressure on proposals.",
        "capabilities": ["market_sim.critique"],
        "authority": {"may_propose": False, "may_order": False, "may_veto": True},
        "output_contract": ["counterargument", "risk_flag"],
        "budget": {"max_model_calls": 6, "max_tokens": 3000},
    },
    {
        "key": "risk_agent",
        "name": "Risk Officer",
        "kind": "specialist",
        "role": "risk_agent",
        "tags": ["trading", "market_sim", "risk"],
        "description": "Hard veto on orders; cannot be bypassed by model output.",
        "capabilities": ["market_sim.risk_veto"],
        "authority": {"may_propose": False, "may_order": False, "may_veto": True, "veto_is_binding": True},
        "output_contract": ["veto", "limit_check"],
        "budget": {"max_model_calls": 4, "max_tokens": 2000},
    },
    {
        "key": "portfolio_manager",
        "name": "Portfolio Manager",
        "kind": "specialist",
        "role": "portfolio_manager",
        "tags": ["trading", "market_sim"],
        "description": "Manages shared portfolio when game mode is collaborative.",
        "capabilities": ["market_sim.portfolio"],
        "authority": {"may_propose": True, "may_order": True, "may_veto": False, "shared_book": True},
        "output_contract": ["allocation", "order_intent"],
        "budget": {"max_model_calls": 6, "max_tokens": 3000},
    },
    {
        "key": "evaluator",
        "name": "Independent Evaluator",
        "kind": "specialist",
        "role": "evaluator",
        "tags": ["trading", "market_sim", "evaluation"],
        "description": "Out-of-sample evaluation; does not trade during design window.",
        "capabilities": ["market_sim.evaluate"],
        "authority": {"may_propose": False, "may_order": False, "may_veto": False, "independent": True},
        "output_contract": ["metrics", "accept_or_reject", "error_analysis"],
        "budget": {"max_model_calls": 4, "max_tokens": 4000},
    },
    {
        "key": "trading_orchestrator",
        "name": "Trading Orchestrator",
        "kind": "orchestrator",
        "role": "trading_orchestrator",
        "tags": ["trading", "market_sim", "orchestrator"],
        "description": "Owns research task status, deadlines, iteration caps, stop criteria.",
        "capabilities": ["market_sim.orchestrate"],
        "authority": {
            "may_propose": False,
            "may_order": False,
            "may_veto": False,
            "manages_task": True,
            "cannot_enable_live": True,
        },
        "output_contract": ["task_status", "stop_decision", "assignment"],
        "budget": {"max_iterations": 8, "max_model_calls": 12, "max_tokens": 8000},
    },
]


# Map legacy sim roles → fleet role keys
LEGACY_ROLE_MAP = {
    AgentRole.TREND.value: "market_analyst",
    AgentRole.MEAN_REVERSION.value: "strategy_researcher",
    AgentRole.RISK_OFFICER.value: "risk_agent",
    AgentRole.CRITIC.value: "critic",
    AgentRole.ALLOCATOR.value: "portfolio_manager",
    AgentRole.EVENT_MACRO.value: "market_analyst",
}


def default_competition_agents(*, initial_cash: float = 100_000.0) -> list[dict[str, Any]]:
    """Two trading agents + orchestrator metadata for E2E demos."""
    return [
        {
            "agent_id": "agent-alpha",
            "role": "market_analyst",
            "label": "Alpha (trend)",
            "parameters": {"fast_ma": 8, "slow_ma": 21, "lookback": 30},
            "initial_cash": initial_cash,
            "authority": {"may_order": True},
        },
        {
            "agent_id": "agent-beta",
            "role": "strategy_researcher",
            "label": "Beta (mean-reversion)",
            "parameters": {"lookback": 20, "entry_z": -1.2, "exit_z": 0.2},
            "entry_rules": {"kind": "mean_reversion", "entry_z": -1.2},
            "exit_rules": {"kind": "mean_reversion", "exit_z": 0.2},
            "initial_cash": initial_cash,
            "authority": {"may_order": True},
        },
        {
            "agent_id": "agent-risk",
            "role": "risk_agent",
            "label": "Risk Officer",
            "parameters": {},
            "initial_cash": 0.0,
            "authority": {"may_order": False, "may_veto": True, "veto_is_binding": True},
        },
        {
            "agent_id": "agent-orch",
            "role": "trading_orchestrator",
            "label": "Orchestrator",
            "parameters": {},
            "initial_cash": 0.0,
            "authority": {"manages_task": True, "cannot_enable_live": True},
        },
    ]


def ensure_trading_agents_in_fleet(fleet: Any) -> list[dict[str, Any]]:
    """Idempotently register trading roles on the existing Agent Fleet."""
    created = []
    if fleet is None:
        return created
    existing = {a.name.lower(): a for a in fleet.list_agents(include_archived=True)}
    for spec in TRADING_ROLE_SPECS:
        if spec["name"].lower() in existing:
            continue
        try:
            agent = fleet.create_agent(
                {
                    "name": spec["name"],
                    "kind": spec["kind"],
                    "role": spec["role"],
                    "description": spec["description"],
                    "tags": list(spec["tags"]),
                    "capabilities": list(spec["capabilities"]),
                    "metadata": {
                        "trading_role": True,
                        "authority": spec["authority"],
                        "output_contract": spec["output_contract"],
                        "budget": spec["budget"],
                    },
                }
            )
            created.append(agent.public_dict() if hasattr(agent, "public_dict") else {"name": spec["name"]})
        except Exception:  # noqa: BLE001
            # Fleet API shape may vary; skip rather than crash control plane
            continue
    return created
