"""Pillar 6 — Agent / User Mental Models.

Operational collaboration models only. No psychological profiling.
User model stays narrow: explicit preferences, goals, constraints, autonomy.
"""

from __future__ import annotations

from typing import Any

from .contracts import AdaptiveDecision, utc_now
from .modes import CognitiveMode, mode_allows_influence


# Forbidden inference categories — never store or infer.
FORBIDDEN_USER_ATTRIBUTES = frozenset(
    {
        "politics",
        "health",
        "psychology",
        "religion",
        "sexuality",
        "ethnicity",
        "sensitive_personal",
    }
)


def update_agent_model(
    store: Any,
    *,
    agent_id: str,
    capabilities: list[str] | None = None,
    tools: list[str] | None = None,
    model: str | None = None,
    outcome: dict[str, Any] | None = None,
    mode: CognitiveMode = CognitiveMode.SHADOW,
) -> dict[str, Any]:
    """Update operational agent model from recorded outcomes only."""
    prior = store.get_agent_model(agent_id) if store else None
    record = dict(prior or {})
    record["agent_id"] = agent_id
    if capabilities is not None:
        record["capabilities"] = list(capabilities)
    if tools is not None:
        record["tools"] = list(tools)
    if model is not None:
        record["model"] = model

    stats = dict(record.get("stats") or {})
    stats.setdefault("attempts", 0)
    stats.setdefault("verified_successes", 0)
    stats.setdefault("failures", 0)
    stats.setdefault("latency_ms_sum", 0)
    stats.setdefault("cost_sum", 0.0)
    failure_patterns = list(record.get("failure_patterns") or [])
    domain_scores = dict(record.get("domain_scores") or {})

    if outcome:
        stats["attempts"] = int(stats["attempts"]) + 1
        verified = bool(outcome.get("verified_success") or outcome.get("success"))
        if verified:
            stats["verified_successes"] = int(stats["verified_successes"]) + 1
        else:
            stats["failures"] = int(stats["failures"]) + 1
            pattern = str(outcome.get("failure_pattern") or outcome.get("error_class") or "unknown_failure")
            if pattern not in failure_patterns:
                failure_patterns.append(pattern)
            failure_patterns = failure_patterns[-20:]
        if outcome.get("latency_ms") is not None:
            stats["latency_ms_sum"] = int(stats["latency_ms_sum"]) + int(outcome["latency_ms"])
        if outcome.get("cost") is not None:
            stats["cost_sum"] = float(stats["cost_sum"]) + float(outcome["cost"])
        domain = str(outcome.get("domain") or "").strip()
        if domain:
            ds = dict(domain_scores.get(domain) or {"attempts": 0, "verified_successes": 0})
            ds["attempts"] = int(ds["attempts"]) + 1
            if verified:
                ds["verified_successes"] = int(ds["verified_successes"]) + 1
            domain_scores[domain] = ds

    attempts = max(1, int(stats["attempts"]))
    record["stats"] = stats
    record["failure_patterns"] = failure_patterns
    record["domain_scores"] = domain_scores
    record["known_limitations"] = list(record.get("known_limitations") or [])
    record["success_rate"] = round(int(stats["verified_successes"]) / attempts, 4)
    record["avg_latency_ms"] = round(int(stats["latency_ms_sum"]) / attempts, 2) if stats["latency_ms_sum"] else None
    record["updated_at"] = utc_now()
    record["source"] = "verified_outcomes"

    influence = mode_allows_influence(mode)
    if influence and store is not None:
        record = store.upsert_agent_model(agent_id, record)

    return {
        "agent_model": record,
        "persisted": influence,
        "decision": AdaptiveDecision(
            controller="cognitive.mental_models",
            decision="update_agent" if influence else "shadow_update",
            reason_code="VERIFIED_OUTCOME",
            mode=mode.value,
            input_refs=[agent_id],
        ).to_dict(),
    }


def rank_agents_for_task(
    store: Any,
    *,
    domain: str,
    required_tools: list[str] | None = None,
    policy_allowed: list[str] | None = None,
) -> dict[str, Any]:
    """Rank agents by verified domain performance without overriding policy."""
    required_tools = required_tools or []
    policy_allowed = set(policy_allowed) if policy_allowed is not None else None
    agents = store.list_agent_models() if store else []
    ranked = []
    for agent in agents:
        agent_id = str(agent.get("agent_id") or "")
        if policy_allowed is not None and agent_id not in policy_allowed:
            continue
        tools = set(agent.get("tools") or [])
        if required_tools and not set(required_tools).issubset(tools):
            continue
        domain_stats = (agent.get("domain_scores") or {}).get(domain) or {}
        attempts = int(domain_stats.get("attempts") or 0)
        successes = int(domain_stats.get("verified_successes") or 0)
        # One failure must not permanently poison — require decayed/aggregated evidence
        score = (successes / attempts) if attempts >= 2 else (agent.get("success_rate") or 0.0) * 0.5
        ranked.append(
            {
                "agent_id": agent_id,
                "score": round(float(score), 4),
                "attempts": attempts,
                "verified_successes": successes,
                "failure_patterns": list(agent.get("failure_patterns") or [])[:5],
                "model": agent.get("model"),
            }
        )
    ranked.sort(key=lambda x: (-x["score"], -x["attempts"], x["agent_id"]))
    return {
        "domain": domain,
        "ranked": ranked,
        "policy_respected": True,
        "decision": AdaptiveDecision(
            controller="cognitive.mental_models",
            decision="rank_agents",
            reason_code="VERIFIED_PERFORMANCE_HISTORY",
            mode=CognitiveMode.SHADOW.value,
            input_refs=[domain],
        ).to_dict(),
    }


def build_user_model(
    *,
    project_package: dict[str, Any] | None = None,
    explicit_preferences: dict[str, Any] | None = None,
    autonomy_level: str | None = None,
    policies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Narrow functional user/project model — explicit data only."""
    package = project_package or {}
    prefs = dict(explicit_preferences or {})
    # Strip any forbidden attributes if somehow provided
    for key in list(prefs.keys()):
        if key.lower() in FORBIDDEN_USER_ATTRIBUTES:
            prefs.pop(key, None)

    goals = []
    decisions = []
    constraints = []
    assumptions = []
    for item in package.get("items") or package.get("goals") or []:
        if isinstance(item, dict):
            kind = str(item.get("kind") or item.get("type") or "")
            if kind == "goal" or item.get("is_goal"):
                goals.append({"id": item.get("id"), "text": item.get("text") or item.get("content")})
            elif kind == "decision":
                decisions.append({"id": item.get("id"), "text": item.get("text") or item.get("content")})
            elif kind == "constraint":
                constraints.append({"id": item.get("id"), "text": item.get("text") or item.get("content")})
            elif kind == "assumption":
                assumptions.append({"id": item.get("id"), "text": item.get("text") or item.get("content")})
    # Project continuity context_package shape
    for key, bucket in (
        ("goals", goals),
        ("decisions", decisions),
        ("constraints", constraints),
        ("assumptions", assumptions),
    ):
        for item in package.get(key) or []:
            if isinstance(item, dict) and item not in bucket:
                bucket.append({"id": item.get("id"), "text": item.get("text") or item.get("content") or item.get("statement")})

    return {
        "kind": "user_operational_model",
        "explicit_preferences": prefs,
        "current_project_goals": goals,
        "approved_architectural_decisions": decisions,
        "constraints": constraints,
        "assumptions": assumptions,
        "desired_autonomy_level": autonomy_level or package.get("autonomy_level") or "default",
        "explicit_policies": dict(policies or {}),
        "inferred_sensitive_attributes": None,  # explicitly never inferred
        "updated_at": utc_now(),
        "decision": AdaptiveDecision(
            controller="cognitive.mental_models",
            decision="user_model_snapshot",
            reason_code="EXPLICIT_PROJECT_CONTINUITY",
            mode=CognitiveMode.ACTIVE.value,
        ).to_dict(),
    }
