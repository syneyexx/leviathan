"""Hybrid, cost-aware, explainable capability ranking.

Staged reduction:
full registry → cheap metadata/lexical filter → optional semantic rerank
→ policy/trust/health filter → small candidate set.
A model is never consulted from this module.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .contracts import CanonicalCapability, RankedCandidate, RequirementPlan, RoutingDecision
from .taxonomy import COST_RANK, LATENCY_RANK, SIDE_EFFECT_RANK

_TOKEN = re.compile(r"[a-zA-ZÀ-ÿ0-9_.-]+")

# Weights are documented so routing remains inspectable.
WEIGHTS = {
    "exact_reference": 40.0,
    "lexical": 4.0,
    "semantic": 2.0,
    "intent": 8.0,
    "domain": 6.0,
    "kind_match": 10.0,
    "prerequisite": 4.0,
    "health_available": 4.0,
    "health_degraded": 1.0,
    "reliability": 3.0,
    "agent_affinity": 3.0,
    "cost": -3.0,
    "latency": -1.5,
    "side_effect": -2.0,
    "model_kind_penalty": -6.0,
    "failure": -12.0,
    "data_locality": 3.0,
    "token_overhead": -2.0,
}

# Deterministic synonym expansion — not embeddings, not a model call.
_SEMANTIC_EXPAND = {
    "race": ("concurrency", "deadlock", "thread", "lock"),
    "deadlock": ("concurrency", "lock", "race"),
    "bug": ("repair", "debug", "diagnose"),
    "fix": ("repair", "patch", "debug"),
    "prove": ("verify", "test"),
    "mutex": ("lock", "concurrency"),
    # Document conversion (MarkItDown and similar) — NL + EN task language.
    "pdf": ("markdown", "convert", "document", "markitdown", "docx", "office"),
    "markdown": ("convert", "pdf", "document", "markitdown", "md"),
    "marktdown": ("markdown", "convert", "markitdown"),
    "omzetten": ("convert", "markdown", "pdf", "document"),
    "converteren": ("convert", "markdown", "pdf", "document"),
    "convert": ("markdown", "pdf", "document", "markitdown"),
    "document": ("pdf", "markdown", "convert", "office"),
    "docx": ("office", "convert", "markdown", "document"),
    # Browser automation (Puppeteer and similar).
    "screenshot": ("browser", "puppeteer", "chromium", "navigate", "website"),
    "browser": ("puppeteer", "screenshot", "navigate", "chromium", "fetch"),
    "website": ("browser", "navigate", "puppeteer", "url", "screenshot"),
    "navigatie": ("navigate", "browser", "puppeteer"),
    "navigate": ("browser", "puppeteer", "url", "website"),
    "puppeteer": ("browser", "screenshot", "chromium", "navigate"),
    # Issue trackers / MCP-style provider language.
    "github": ("issue", "pull", "repository", "mcp"),
    "issue": ("github", "ticket", "bug"),
}

INTENT_ALIASES = {
    "code.search": {"inspect_code", "code.search", "repository.read"},
    "repository.read": {"inspect_code", "code.search", "repository.read"},
    "code.modify": {"code.modify", "repair_bug", "patch_generation"},
    "tests.execute": {"tests.execute", "result.verify"},
    "result.verify": {"result.verify", "tests.execute"},
    "software.reason": {"diagnose_bug", "repair_bug", "debugging", "software.reason"},
}


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in _TOKEN.findall(text or "") if len(item) > 1}


def semantic_tokens(query: str) -> set[str]:
    tokens = _tokens(query)
    extra: set[str] = set()
    for token in tokens:
        extra.update(_SEMANTIC_EXPAND.get(token, ()))
    return tokens | extra


def _wanted_intents(plan: RequirementPlan | None) -> set[str]:
    if plan is None:
        return set()
    wanted: set[str] = set()
    for item in plan.requirements:
        wanted.add(item.capability)
        wanted.update(INTENT_ALIASES.get(item.capability, {item.capability}))
    return wanted


def lexical_overlap(query: str, capability: CanonicalCapability) -> tuple[float, float]:
    tokens = _tokens(query)
    blob = " ".join(
        [
            capability.name,
            capability.description,
            capability.canonical_id,
            " ".join(capability.domains),
            " ".join(capability.intents),
            " ".join(capability.aliases),
            capability.provider_id,
            capability.plugin_id or "",
        ]
    )
    overlap = len(tokens & _tokens(blob))
    semantic = len((semantic_tokens(query) - tokens) & _tokens(blob))
    return float(overlap), float(semantic)


def exact_reference(query: str, capability: CanonicalCapability, explicit: list[str] | None = None) -> float:
    hay = query.lower()
    names = [capability.name, capability.canonical_id, *(capability.aliases), capability.plugin_id or "", capability.provider_id]
    for name in names:
        text = str(name or "").strip().lower()
        if text and len(text) >= 3 and text in hay:
            return 1.0
    for item in explicit or []:
        needle = item.lower()
        if any(needle in str(name or "").lower() or str(name or "").lower() in needle for name in names if name):
            return 1.0
    return 0.0


def score_capability(
    query: str,
    capability: CanonicalCapability,
    *,
    plan: RequirementPlan | None = None,
    metrics: dict[str, Any] | None = None,
    known_dead: set[str] | None = None,
) -> RankedCandidate:
    components: dict[str, float] = {}
    reasons: list[str] = []
    explicit = plan.explicit_providers if plan else []
    exact = exact_reference(query, capability, explicit)
    components["exact_reference"] = WEIGHTS["exact_reference"] * exact
    if exact:
        reasons.append("exact_reference")
    lex, semantic = lexical_overlap(query, capability)
    components["lexical"] = WEIGHTS["lexical"] * lex
    components["semantic"] = WEIGHTS["semantic"] * semantic
    if lex:
        reasons.append("lexical_relevance")
    if semantic:
        reasons.append("semantic_relevance")
    intent_hits = 0
    domain_hits = 0
    kind_hits = 0
    if plan:
        wanted_intents = _wanted_intents(plan)
        intent_hits = len(wanted_intents & set(capability.intents))
        if capability.canonical_id in wanted_intents or any(
            item in capability.canonical_id for item in wanted_intents if len(item) >= 8
        ):
            intent_hits += 1
        domain_hits = len(set(capability.domains) & set(plan.domains))
        wanted_kinds = {item.kind_hint for item in plan.requirements if item.kind_hint}
        kind_hits = 1 if capability.kind in wanted_kinds else 0
        extras = capability.extras.get("agent") or {}
        accepts = {str(value).lower() for value in extras.get("accepts") or []}
        if accepts & {"diagnosis", "analysis", "patch_generation", "coding_task", "debugging_task", "verification"}:
            if any(item.capability in {"software.reason", "code.modify", "result.verify"} for item in plan.requirements):
                intent_hits += 1
    # Kind bonus only when another signal exists — do not rank every tool because the plan wants a tool.
    kind_bonus = WEIGHTS["kind_match"] * kind_hits if (intent_hits or domain_hits or lex or exact) else 0.0
    components["intent"] = WEIGHTS["intent"] * intent_hits
    components["domain"] = WEIGHTS["domain"] * domain_hits
    components["kind_match"] = kind_bonus
    if intent_hits:
        reasons.append("intent_match")
    if domain_hits:
        reasons.append("domain_match")
        if capability.kind in {"skill", "knowledge"} and (intent_hits or domain_hits or lex or semantic or exact):
            reasons.append("reasoning_guidance")
    health = capability.health
    if health == "available":
        components["health"] = WEIGHTS["health_available"]
        reasons.append("provider_healthy")
    elif health == "degraded":
        components["health"] = WEIGHTS["health_degraded"]
        reasons.append("provider_degraded")
    else:
        components["health"] = 0.0
    components["cost"] = WEIGHTS["cost"] * COST_RANK.get(capability.cost_class, 1)
    components["latency"] = WEIGHTS["latency"] * LATENCY_RANK.get(capability.latency_class, 1)
    components["side_effect"] = WEIGHTS["side_effect"] * SIDE_EFFECT_RANK.get(capability.side_effect_class, 0)
    if capability.kind in {"agent", "workflow"}:
        components["model_kind_penalty"] = WEIGHTS["model_kind_penalty"]
    metrics = metrics or {}
    attempts = int(metrics.get("attempts") or 0)
    verified = int(metrics.get("verified_successes") or 0)
    if attempts >= 3:
        rate = verified / max(attempts, 1)
        components["reliability"] = WEIGHTS["reliability"] * (rate - 0.5)
        if rate >= 0.6:
            reasons.append("verified_history_strong")
    dead = known_dead or set()
    if capability.canonical_id in dead or capability.provider_id in dead:
        components["failure"] = WEIGHTS["failure"]
        reasons.append("known_failure")
    locality = str(capability.extras.get("data_locality") or capability.extras.get("locality") or "")
    if locality in {"local", "same_node"}:
        components["data_locality"] = WEIGHTS["data_locality"]
        reasons.append("data_locality")
    tool_count = 0
    try:
        tool_count = int(capability.extras.get("tool_count") or 0)
    except (TypeError, ValueError):
        tool_count = 0
    if tool_count > 40:
        components["token_overhead"] = WEIGHTS["token_overhead"] * min(3.0, tool_count / 40.0)
        reasons.append("large_tool_surface")
    score = sum(components.values())
    # Kind-only or health-only hits are not a routing signal.
    if exact == 0 and lex <= 0 and semantic <= 0 and intent_hits == 0 and domain_hits == 0:
        score = 0.0
        reasons = ["no_signal"]
    return RankedCandidate(capability=capability, score=score, eligible=True, reasons=reasons, components=components)


def rank_capabilities(
    query: str,
    capabilities: Iterable[CanonicalCapability],
    *,
    plan: RequirementPlan | None = None,
    metrics_by_id: dict[str, dict[str, Any]] | None = None,
    known_dead: set[str] | None = None,
    limit: int = 8,
) -> RoutingDecision:
    ranked: list[RankedCandidate] = []
    for capability in capabilities:
        ranked.append(
            score_capability(
                query,
                capability,
                plan=plan,
                metrics=(metrics_by_id or {}).get(capability.canonical_id),
                known_dead=known_dead,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.capability.cost_class, item.capability.name))
    selected = [item for item in ranked if item.score > 0][:limit]
    rejected = [item for item in ranked if item.score <= 0][:24]
    explicit_honored = bool(plan and plan.explicit_providers and any("exact_reference" in item.reasons for item in selected))
    explanation = "deterministic_hybrid_ranker"
    if explicit_honored:
        explanation = "explicit_provider_honored"
    return RoutingDecision(
        selected=selected,
        rejected=rejected,
        considered=len(ranked),
        model_called=False,
        explicit_honored=explicit_honored,
        explanation=explanation,
    )


def cover_kinds(candidates: list[RankedCandidate], *, limit: int) -> list[RankedCandidate]:
    """Keep skill/agent/tool coverage when truncating a high-scoring native-tool pile."""
    if len(candidates) <= limit:
        return list(candidates)
    picked: list[RankedCandidate] = []
    used: set[str] = set()
    quotas = (("skill", 1), ("agent", 3), ("tool", 3), ("knowledge", 1), ("workflow", 1))

    def take(kind: str, quota: int) -> None:
        n = 0
        pool = [item for item in candidates if item.capability.kind == kind]
        if kind == "agent":
            plugin_first = [item for item in pool if item.capability.plugin_id]
            native = [item for item in pool if not item.capability.plugin_id]
            native.sort(key=lambda item: 0 if item.capability.canonical_id == "hades.verification" else 1)
            pool = plugin_first + native
        for item in pool:
            if n >= quota or len(picked) >= limit:
                return
            if item.capability.canonical_id in used:
                continue
            picked.append(item)
            used.add(item.capability.canonical_id)
            n += 1

    for kind, quota in quotas:
        take(kind, quota)
    for item in candidates:
        if len(picked) >= limit:
            break
        if item.capability.canonical_id in used:
            continue
        picked.append(item)
        used.add(item.capability.canonical_id)
    return picked
