"""Project domain roles onto the canonical HADES agent protocol."""

from __future__ import annotations

from typing import Any

from capability_intel.contracts import AgentContract
from capability_intel.taxonomy import DEFAULT_BUDGETS

from .contracts import CanonicalAgent


def from_agent_contract(contract: AgentContract, *, domain: str = "generic", responsibility: str = "") -> CanonicalAgent:
    return CanonicalAgent(
        identity=contract.canonical_id,
        responsibility=responsibility or ",".join(contract.specialties) or contract.canonical_id,
        domain=domain,
        role_id=str(contract.extras.get("role_id") or ""),
        capabilities=list(contract.allowed_capabilities),
        required_inputs=list(contract.required_context),
        expected_outputs=list(contract.produces),
        context_requirements=list(contract.required_context),
        allowed_tools=list(contract.allowed_capabilities),
        model_preferences={"cost_class": contract.cost_class, "latency_class": contract.latency_class},
        budgets=dict(DEFAULT_BUDGETS),
        acceptance_criteria=list(contract.produces),
        recovery=str(contract.extras.get("recovery") or ""),
        authority_limits=list(contract.extras.get("forbidden") or []),
        contract=contract,
        extras=dict(contract.extras),
    )


def from_trading_role(role: Any) -> CanonicalAgent:
    """Trading Lab AgentRole remains a domain role; this is a projection only."""
    role_id = str(getattr(role, "role_id", "") or "")
    reads = list(getattr(role, "reads", ()) or ())
    writes = list(getattr(role, "writes", ()) or ())
    forbidden = list(getattr(role, "forbidden", ()) or ())
    contract = AgentContract(
        canonical_id=f"trading.lab.{role_id}",
        specialties=["trading", role_id],
        accepts=["trading_lab_task"],
        produces=list((getattr(role, "output_schema", {}) or {}).keys()),
        required_context=reads,
        allowed_capabilities=reads + writes,
        cost_class="moderate",
        extras={"forbidden": forbidden, "role_id": role_id, "domain_truth": "trading_lab"},
    )
    agent = from_agent_contract(contract, domain="trading", responsibility=str(getattr(role, "mandate", "") or role_id))
    agent.authority_limits = forbidden
    agent.allowed_tools = reads + writes
    agent.extras["deterministic_forbidden"] = ["fills", "risk_veto", "ledger"]
    return agent


def from_coding_specialist(*, identity: str, responsibility: str, allowed_tools: list[str], limits: list[str] | None = None) -> CanonicalAgent:
    contract = AgentContract(
        canonical_id=identity,
        specialties=["coding"],
        accepts=["coding_task"],
        produces=["findings", "patch", "test_results"],
        allowed_capabilities=allowed_tools,
        extras={"forbidden": list(limits or []), "role_id": identity},
    )
    return from_agent_contract(contract, domain="coding", responsibility=responsibility)


def from_media_role(*, identity: str, responsibility: str, allowed_tools: list[str]) -> CanonicalAgent:
    contract = AgentContract(
        canonical_id=identity,
        specialties=["media"],
        accepts=["media_task"],
        produces=["storyboard", "render", "publish_result"],
        allowed_capabilities=allowed_tools,
        extras={"role_id": identity},
    )
    return from_agent_contract(contract, domain="media", responsibility=responsibility)


def from_research_worker(*, identity: str = "research.worker") -> CanonicalAgent:
    contract = AgentContract(
        canonical_id=identity,
        specialties=["research"],
        accepts=["research_task"],
        produces=["citations", "evidence", "report"],
        allowed_capabilities=["retrieve", "fetch", "cite"],
    )
    return from_agent_contract(contract, domain="research", responsibility="Gather and cite sources")


def justify_additional_agent(*, unique_capability: bool, specialist: bool, parallel: bool, independent_verify: bool, authority_separation: bool, information_gain: bool) -> str | None:
    """Return a recorded reason or None — never spawn an agent because a named role exists."""
    if unique_capability:
        return "unique_capability"
    if specialist:
        return "specialist_expertise"
    if parallel:
        return "safe_parallelism"
    if independent_verify:
        return "independent_verification"
    if authority_separation:
        return "authority_separation"
    if information_gain:
        return "information_gain"
    return None
