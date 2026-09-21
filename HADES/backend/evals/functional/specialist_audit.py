"""Honest specialist classification — contracts vs true engines.

Classes:
  PROMPT_SPECIALIST — different prompt/profile only
  TOOL_SPECIALIST — different tool/capability set
  RUNTIME_SPECIALIST — different execution loop
  DOMAIN_ENGINE — specialized deterministic subsystem
"""

from __future__ import annotations

from typing import Any, Literal

from evals.harness import git_start_commit

EngineClass = Literal["PROMPT_SPECIALIST", "TOOL_SPECIALIST", "RUNTIME_SPECIALIST", "DOMAIN_ENGINE"]

SPECIALIST_AUDIT_VERSION = "specialist_audit_v1"

# Measured advantage is UNKNOWN until scoreboard rows exist — do not invent rates.
_ENGINE_CLASS: dict[str, EngineClass] = {
    "chat": "PROMPT_SPECIALIST",
    "executor": "PROMPT_SPECIALIST",
    "researcher": "TOOL_SPECIALIST",
    "analyst": "PROMPT_SPECIALIST",
    "coder": "RUNTIME_SPECIALIST",  # coding loop may attach
    "reviewer": "PROMPT_SPECIALIST",
    "verifier": "TOOL_SPECIALIST",
    "memory_curator": "TOOL_SPECIALIST",
    "build": "DOMAIN_ENGINE",
    "research_worker": "RUNTIME_SPECIALIST",
    "plugin_converter": "TOOL_SPECIALIST",
    "trading": "DOMAIN_ENGINE",
    "voice": "DOMAIN_ENGINE",
}

# Domain engines known outside the SPECIALISTS registry
_EXTRA_ENGINES: list[dict[str, Any]] = [
    {
        "agent_id": "coding_agent_runtime",
        "engine_class": "DOMAIN_ENGINE",
        "reason": "worktrees, patching, tests, repair waves — backend/coding_agent.py",
        "measured_advantage": None,
    },
    {
        "agent_id": "trading_lab",
        "engine_class": "DOMAIN_ENGINE",
        "reason": "ledger/risk/backtest simulation — backend/trading_lab/",
        "measured_advantage": None,
    },
]


def classify_specialists() -> dict[str, Any]:
    from reasoning.specialists import SPECIALISTS, list_active_specialists

    sha = git_start_commit()
    rows: list[dict[str, Any]] = []
    for spec in list_active_specialists(include_planned=True):
        agent_id = spec.agent_id
        engine = str(getattr(spec, "engine_class", None) or _ENGINE_CLASS.get(agent_id) or "PROMPT_SPECIALIST")
        rows.append(
            {
                "agent_id": agent_id,
                "name": spec.name,
                "engine_class": engine,
                "deterministic": spec.deterministic,
                "planned_only": spec.planned_only,
                "capabilities": list(spec.capabilities),
                "allowed_tools": list(spec.allowed_tools),
                "sample_size": 0,
                "success_rate": None,
                "latency": None,
                "cost": None,
                "special_advantage": None,
                "honesty": "No measured advantage claimed without benchmark rows.",
            }
        )
    for extra in _EXTRA_ENGINES:
        rows.append(
            {
                **extra,
                "name": extra["agent_id"],
                "deterministic": True,
                "planned_only": False,
                "capabilities": [],
                "allowed_tools": [],
                "sample_size": 0,
                "success_rate": None,
                "latency": None,
                "cost": None,
                "special_advantage": None,
                "honesty": "No measured advantage claimed without benchmark rows.",
            }
        )

    by_class: dict[str, list[str]] = {}
    for row in rows:
        by_class.setdefault(row["engine_class"], []).append(row["agent_id"])

    return {
        "suite": "specialist_audit",
        "version": SPECIALIST_AUDIT_VERSION,
        "git_sha": sha,
        "registry_count": len(SPECIALISTS),
        "by_class": by_class,
        "specialists": rows,
        "routing_policy": [
            "Use specialist only for unique capability, measured performance,",
            "special tool access, independent verification, parallelism, or domain engine need.",
            "Do not spawn N agents because N profiles exist.",
        ],
        "status": "PASS",
    }
