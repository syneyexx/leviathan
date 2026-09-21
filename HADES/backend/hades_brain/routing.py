"""Staged capability routing with marketplace fallback. No routing LLM."""

from __future__ import annotations

from typing import Any, Callable

from capability_intel.contracts import RequirementPlan, RoutingDecision
from capability_intel.planner import plan_requirements
from capability_intel.ranking import rank_capabilities
from capability_intel.service import CapabilityIntelligence, get_service

from .cost import get_ledger
from .observability import decision_record


def route_local(
    query: str,
    capabilities: list[Any] | None = None,
    *,
    intel: CapabilityIntelligence | None = None,
    plugins_by_id: dict[str, dict[str, Any]] | None = None,
    tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    permission_ok: Callable[..., bool] | None = None,
    known_dead: set[str] | None = None,
    limit: int = 8,
) -> tuple[RequirementPlan, RoutingDecision]:
    if capabilities is not None:
        plan = plan_requirements(query)
        decision = rank_capabilities(query, capabilities, plan=plan, known_dead=known_dead, limit=limit)
        return plan, decision
    service = intel or get_service()
    return service.route(
        query,
        plugins_by_id=plugins_by_id,
        tools_by_key=tools_by_key,
        settings=settings,
        permission_ok=permission_ok,
        known_dead=known_dead,
        limit=limit,
    )


def needs_external_discovery(plan: RequirementPlan, decision: RoutingDecision) -> bool:
    if plan.simple:
        return False
    if plan.explicit_providers:
        return False
    eligible = [item for item in decision.selected if item.eligible]
    return len(eligible) == 0


def brain_route(
    query: str,
    *,
    intel: CapabilityIntelligence | None = None,
    marketplace_search: Callable[[str], dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    plan, decision = route_local(query, intel=intel, **kwargs)
    ledger = get_ledger()
    if decision.model_called:
        ledger.record_unnecessary_model_call("capability_routing_must_be_deterministic")
    payload: dict[str, Any] = {
        "plan": plan.to_dict(),
        "routing": decision.to_dict(),
        "model_called": False,
        "routing_model_calls": 0,
        "marketplace": None,
        "decision": decision_record(
            capability=plan.requirements[0].capability if plan.requirements else None,
            provider=(decision.selected[0].capability.provider_id if decision.selected else None),
            model_call_reason=None,
            cache="reused" if decision.reused_cache else "miss",
            extras={"explicit_honored": decision.explicit_honored, "simple": plan.simple},
        ),
    }
    if decision.reused_cache:
        ledger.add(cache_hits=1)
    else:
        ledger.add(cache_misses=1)
    if not needs_external_discovery(plan, decision):
        return payload
    if marketplace_search is None:
        payload["marketplace"] = {"status": "skipped", "reason": "no_connector"}
        return payload
    try:
        market = marketplace_search(query)
    except Exception as exc:
        payload["marketplace"] = {"status": "unavailable", "error": type(exc).__name__, "model_called": False}
        return payload
    payload["marketplace"] = market
    payload["decision"]["why_capability"] = payload["decision"].get("why_capability") or "missing_local_provider"
    return payload
