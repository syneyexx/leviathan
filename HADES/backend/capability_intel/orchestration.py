"""Safe orchestration: composition, roles, mutation ownership, fallback, verification."""

from __future__ import annotations

from typing import Any, Iterable

from .contracts import CanonicalCapability, RankedCandidate, RequirementPlan, RoutingDecision
from .collaboration import CollaborationSession, MissionState, compact_handoff, targeted_consultation_context
from .taxonomy import AGENT_ROLES, DEFAULT_BUDGETS, NATIVE_PROVIDER_ID


def _pick(
    candidates: list[RankedCandidate],
    used: set[str],
    predicate,
    *,
    limit: int = 1,
    prefer_unused_providers: set[str] | None = None,
) -> list[RankedCandidate]:
    matching = [row for row in candidates if predicate(row) and row.capability.canonical_id not in used]
    if not matching:
        return []
    best = max(item.score for item in matching)
    band = [item for item in matching if item.score >= best * 0.55]
    unused_pref = prefer_unused_providers or set()

    def sort_key(item: RankedCandidate) -> tuple:
        provider = item.capability.plugin_id or item.capability.provider_id
        unused_plugin = 0 if item.capability.plugin_id and provider not in unused_pref else 1
        return (unused_plugin, -item.score)

    chosen: list[RankedCandidate] = []
    for item in sorted(band, key=sort_key):
        chosen.append(item)
        used.add(item.capability.canonical_id)
        if len(chosen) >= limit:
            break
    return chosen


def smallest_team(candidates: list[RankedCandidate], plan: RequirementPlan) -> list[RankedCandidate]:
    """Cover required kinds with the fewest providers. Extra agents need a distinct reason."""
    if plan.simple:
        skills = [item for item in candidates if item.capability.kind == "skill"][:1]
        knowledge = [item for item in candidates if item.capability.kind in {"tool", "knowledge"}][:1]
        return skills + knowledge
    used: set[str] = set()
    picked: list[RankedCandidate] = []
    used_providers: set[str] = set()

    def remember(rows: list[RankedCandidate]) -> None:
        for item in rows:
            picked.append(item)
            used_providers.add(item.capability.plugin_id or item.capability.provider_id)

    wanted = {item.capability for item in plan.requirements}
    if any(item.kind_hint == "skill" or item.capability == "software.reason" for item in plan.requirements):
        remember(_pick(candidates, used, lambda row: row.capability.kind == "skill", prefer_unused_providers=used_providers))

    plugin_agents = [item for item in candidates if item.capability.kind == "agent" and item.capability.plugin_id]
    native_agents = [
        item
        for item in candidates
        if item.capability.kind == "agent" and not item.capability.plugin_id and item.capability.canonical_id != "hades.verification"
    ]
    complementary = 0
    max_agents = 1
    distinct_plugins = {item.capability.plugin_id for item in plugin_agents}
    if "code.modify" in wanted and len(distinct_plugins) >= 2:
        max_agents = 2
    elif plan.verification_required and plugin_agents:
        max_agents = min(2, max(1, len(distinct_plugins)))
    seen_plugins: set[str] = set()
    seen_specialties: set[str] = set()
    for item in plugin_agents + native_agents:
        if complementary >= max_agents:
            break
        if item.capability.canonical_id in used:
            continue
        plugin_id = item.capability.plugin_id or item.capability.provider_id
        specialty = ",".join(sorted(item.capability.domains)) or item.capability.canonical_id
        if plugin_id in seen_plugins:
            continue
        if specialty and specialty in seen_specialties and complementary:
            continue
        if item.capability.canonical_id == "hades.coding_agent" and plugin_agents and complementary:
            continue
        seen_plugins.add(plugin_id)
        seen_specialties.add(specialty)
        used.add(item.capability.canonical_id)
        complementary += 1
        remember([item])

    search_intents = {"code.search", "inspect_code", "repository.read"}
    remember(
        _pick(
            candidates,
            used,
            lambda row: row.capability.kind == "tool"
            and (
                search_intents.intersection(row.capability.intents)
                or "read_files" in row.capability.effects
            ),
            prefer_unused_providers=used_providers,
        )
    )
    if plan.verification_required or "result.verify" in wanted or "tests.execute" in wanted:
        remember(
            _pick(
                candidates,
                used,
                lambda row: row.capability.canonical_id == "hades.verification" or (
                    row.capability.kind == "agent" and "verif" in row.capability.name.lower()
                ),
            )
        )
    return picked


def assign_roles(selected: list[RankedCandidate]) -> dict[str, str]:
    roles: dict[str, str] = {}
    agents = [item for item in selected if item.capability.kind == "agent"]
    if not agents:
        return roles
    # Architecture / analysis first, implementation owner for mutation, verifier last.
    remaining = list(AGENT_ROLES)
    for item in agents:
        extras = item.capability.extras.get("agent") or {}
        accepts = {str(value).lower() for value in extras.get("accepts") or []}
        specialties = " ".join(extras.get("specialties") or item.capability.domains).lower()
        domains = " ".join(item.capability.domains).lower() + " " + specialties
        if "diagnos" in domains or "architect" in item.capability.name.lower() or "analysis" in " ".join(accepts):
            roles[item.capability.canonical_id] = "planner" if "planner" not in roles.values() else "specialist"
        elif "implement" in item.capability.name.lower() or "patch" in " ".join(accepts) or "python" in domains:
            roles[item.capability.canonical_id] = "implementation_owner"
        elif item.capability.canonical_id.endswith("verification") or "verif" in item.capability.name.lower():
            roles[item.capability.canonical_id] = "verifier"
        else:
            roles[item.capability.canonical_id] = remaining[min(len(roles), len(remaining) - 1)]
    if sum(1 for value in roles.values() if value == "implementation_owner") > 1:
        # Single mutation owner.
        owners = [key for key, value in roles.items() if value == "implementation_owner"]
        for key in owners[1:]:
            roles[key] = "reviewer"
    if "verifier" not in roles.values():
        native = next((item for item in selected if item.capability.canonical_id == "hades.verification"), None)
        if native:
            roles[native.capability.canonical_id] = "verifier"
    return roles


def choose_mutation_owner(roles: dict[str, str]) -> str | None:
    for canonical_id, role in roles.items():
        if role == "implementation_owner":
            return canonical_id
    return None


def should_consult(plan: RequirementPlan, selected: list[RankedCandidate]) -> bool:
    if plan.simple:
        return False
    agents = [item for item in selected if item.capability.kind == "agent"]
    return len(agents) >= 2 and any("concurren" in " ".join(item.capability.domains).lower() or "debug" in item.capability.name.lower() for item in agents)


def compose_mission(
    query: str,
    capabilities: Iterable[CanonicalCapability],
    *,
    plan: RequirementPlan,
    eligible: list[RankedCandidate],
    mission_id: str,
) -> dict[str, Any]:
    selected = smallest_team(eligible, plan)
    roles = assign_roles(selected)
    owner = choose_mutation_owner(roles)
    decision = RoutingDecision(selected=selected, considered=len(eligible), model_called=False, explicit_honored=plan.explicit_providers != [])
    mission = MissionState(
        mission_id=mission_id,
        goal=plan.goal,
        requirements=[item.capability for item in plan.requirements],
        plan=[item.capability.canonical_id for item in selected],
        assignments=roles,
        mutation_owner=owner,
        budgets=dict(DEFAULT_BUDGETS),
        verification={"required": plan.verification_required, "acceptance": ["deterministic_evidence"]},
    )
    mission.usage["agents"] = sum(1 for item in selected if item.capability.kind == "agent")
    return {
        "mission": mission.to_dict(),
        "routing": decision.to_dict(),
        "roles": roles,
        "mutation_owner": owner,
        "consultation_allowed": should_consult(plan, selected),
        "model_called": False,
    }


def apply_provider_fallback(
    mission: MissionState,
    *,
    failed_provider: str,
    alternatives: list[RankedCandidate],
) -> RankedCandidate | None:
    if failed_provider not in mission.dead_providers:
        mission.dead_providers.append(failed_provider)
    for item in alternatives:
        if item.capability.provider_id == failed_provider or item.capability.canonical_id == failed_provider:
            continue
        if item.capability.provider_id in mission.dead_providers:
            continue
        if not item.eligible:
            continue
        return item
    return None


def verification_result(
    *,
    execution_success: bool,
    evidence: dict[str, Any] | None,
    agent_claims: list[str] | None = None,
) -> dict[str, Any]:
    evidence = evidence or {}
    deterministic = bool(evidence.get("tests_passed") or evidence.get("schema_valid") or evidence.get("build_ok") or evidence.get("lint_ok"))
    independent = bool(evidence.get("independent_review"))
    verified = bool(execution_success and deterministic)
    verifier_model_called = bool((not deterministic) and independent)
    return {
        "execution_success": execution_success,
        "verified_task_success": verified,
        "deterministic_evidence": deterministic,
        "agent_self_report": list(agent_claims or []),
        "agent_self_report_is_proof": False,
        "consensus_is_proof": False,
        "verifier_model_called": verifier_model_called,
        "evidence": evidence,
    }


def native_verifier() -> str:
    return f"{NATIVE_PROVIDER_ID}:hades.verification"


def handoff_payload(session: CollaborationSession, *, task: str) -> dict[str, Any]:
    return compact_handoff(session.mission, task=task)


def consult_payload(question: str, evidence: list[str] | None = None) -> dict[str, Any]:
    return targeted_consultation_context(question, evidence)
