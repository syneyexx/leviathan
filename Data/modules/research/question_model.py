"""Research question model — deterministic with semantic enrichment hooks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import ResearchProject


_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "about",
        "what",
        "how",
        "why",
        "when",
        "where",
        "is",
        "are",
        "was",
        "were",
        "vs",
        "versus",
        "vergelijk",
        "de",
        "het",
        "een",
        "en",
        "van",
        "voor",
        "met",
        "over",
        "wat",
        "hoe",
        "waarom",
        "wanneer",
        "waar",
        "wie",
        "zijn",
        "niet",
        "geen",
    }
)

_COMPARISON_RE = re.compile(
    r"\b(.+?)\b\s+(?:vs\.?|versus|vergelijk(?:en)?(?:\s+met)?|compared\s+to|compared\s+with)\s+\b(.+)",
    re.I,
)
_FRESHNESS_RE = re.compile(
    r"\b(current|currently|latest|newest|recent|up.to.date|actueel|nieuwste|huidige|vandaag)\b",
    re.I,
)
_GEO_RE = re.compile(
    r"\b(in|within|for|in\s+de)\s+([A-ZÀ-Ÿ][A-Za-zÀ-ÿ\-]+(?:\s+[A-ZÀ-Ÿ][A-Za-zÀ-ÿ\-]+){0,2})",
)
_YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?\b")
_QUOTED_RE = re.compile(r"[\"“”']([^\"“”']{2,80})[\"“”']")
_CAPITALIZED_RE = re.compile(r"\b([A-ZÀ-Ÿ][A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-]{1,})\b")


@dataclass
class ResearchQuestionModel:
    original_question: str
    interpreted_question: str
    objective: str
    scope: str
    entities: list[str]
    definitions: list[str]
    temporal_scope: str | None
    geographic_scope: str | None
    assumptions: list[str]
    ambiguities: list[str]
    subquestions: list[str]
    claim_targets: list[str]
    evidence_requirements: list[str]
    source_preferences: list[str]
    exclusions: list[str]
    freshness_requirement: str  # none | preferred | required
    stopping_criteria: list[str]
    comparison_dimensions: list[dict[str, Any]] = field(default_factory=list)
    query_portfolio: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "original_question": self.original_question,
            "interpreted_question": self.interpreted_question,
            "objective": self.objective,
            "scope": self.scope,
            "entities": list(self.entities),
            "definitions": list(self.definitions),
            "temporal_scope": self.temporal_scope,
            "geographic_scope": self.geographic_scope,
            "assumptions": list(self.assumptions),
            "ambiguities": list(self.ambiguities),
            "subquestions": list(self.subquestions),
            "claim_targets": list(self.claim_targets),
            "evidence_requirements": list(self.evidence_requirements),
            "source_preferences": list(self.source_preferences),
            "exclusions": list(self.exclusions),
            "freshness_requirement": self.freshness_requirement,
            "stopping_criteria": list(self.stopping_criteria),
            "comparison_dimensions": [dict(d) for d in self.comparison_dimensions],
            "query_portfolio": list(self.query_portfolio),
        }

    def to_plan_edits(self) -> dict[str, Any]:
        """Map model fields into ResearchPlan-compatible edits."""
        return {
            "interpreted_question": self.interpreted_question,
            "scope": self.scope,
            "assumptions": list(self.assumptions),
            "subquestions": list(self.subquestions),
            "retrieval_queries": list(self.query_portfolio),
            "preferred_source_types": list(self.source_preferences),
            "exclusion_criteria": list(self.exclusions),
            "stopping_criteria": list(self.stopping_criteria),
            "notes": (
                f"question_model entities={len(self.entities)}; "
                f"freshness={self.freshness_requirement}; "
                f"comparison_dims={len(self.comparison_dimensions)}"
            ),
            "evidence_coverage_targets": {
                "prefer_primary_sources": "official_primary" in self.source_preferences
                or "peer_reviewed" in self.source_preferences
                or True,
                "freshness_requirement": self.freshness_requirement,
                "claim_targets": list(self.claim_targets),
                "evidence_requirements": list(self.evidence_requirements),
            },
        }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key:
            continue
        low = key.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(key)
    return out


def _extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    for match in _QUOTED_RE.finditer(text or ""):
        entities.append(match.group(1).strip())
    for match in _CAPITALIZED_RE.finditer(text or ""):
        token = match.group(1)
        if token.lower() in _STOP:
            continue
        if token.isupper() and len(token) <= 2:
            continue
        entities.append(token)
    return _dedupe(entities)[:24]


def _detect_comparison(text: str) -> tuple[str | None, str | None]:
    match = _COMPARISON_RE.search(text or "")
    if not match:
        return None, None
    left = match.group(1).strip(" ?:.,")
    right = match.group(2).strip(" ?:.,")
    # Keep the comparison operands reasonably short.
    left = " ".join(left.split()[-6:])
    right = " ".join(right.split()[:6])
    if len(left) < 2 or len(right) < 2:
        return None, None
    return left, right


def _freshness_requirement(text: str) -> str:
    if not _FRESHNESS_RE.search(text or ""):
        return "none"
    if re.search(r"\b(must|required|alleen|only)\b.*\b(current|latest|nieuwste|actueel)\b", text or "", re.I):
        return "required"
    return "preferred"


def _temporal_scope(text: str) -> str | None:
    match = _YEAR_RANGE_RE.search(text or "")
    if match:
        if match.group(2):
            return f"{match.group(1)}-{match.group(2)}"
        return match.group(1)
    if _FRESHNESS_RE.search(text or ""):
        return "current"
    return None


def _geographic_scope(text: str) -> str | None:
    match = _GEO_RE.search(text or "")
    if match:
        return match.group(2).strip()
    return None


def _comparison_dimensions(left: str, right: str) -> list[dict[str, Any]]:
    dims = [
        "definition_and_scope",
        "capabilities_or_features",
        "performance_or_benchmarks",
        "cost_or_effort",
        "risks_or_limitations",
        "adoption_or_incidents",
        "freshness_or_roadmap",
    ]
    return [
        {
            "dimension": dim,
            "side_a": left,
            "side_b": right,
            "question": f"How do {left} and {right} compare on {dim.replace('_', ' ')}?",
        }
        for dim in dims
    ]


def _build_query_portfolio(
    topic: str,
    entities: list[str],
    *,
    left: str | None,
    right: str | None,
    freshness: str,
) -> list[str]:
    base = topic.strip().rstrip("?")
    portfolio: list[str] = [base] if base else []
    focus = entities[0] if entities else base
    portfolio.extend(
        [
            f"{focus} official documentation",
            f"{focus} technical specification",
            f"{focus} benchmark OR evaluation OR metrics",
            f"{focus} criticism OR limitations OR failures",
            f"{focus} incident OR outage OR vulnerability",
        ]
    )
    if freshness in {"preferred", "required"}:
        portfolio.append(f"{focus} latest changes OR changelog OR recent update")
        portfolio.append(f"{focus} 2024 OR 2025 OR 2026")
    if left and right:
        portfolio.extend(
            [
                f"{left} vs {right}",
                f"{left} compared to {right} benchmark",
                f"{left} {right} differences limitations",
            ]
        )
    for ent in entities[:4]:
        portfolio.append(f"{ent} primary source")
    return _dedupe(portfolio)


def _subquestions_for(
    topic: str,
    objective: str,
    *,
    left: str | None,
    right: str | None,
    dutchish: bool,
) -> list[str]:
    base = topic.strip().rstrip("?")
    if left and right:
        if dutchish:
            return [
                f"Wat is de kerndefinitie van {left} versus {right}?",
                f"Op welke dimensies verschillen {left} en {right} aantoonbaar?",
                f"Welk onafhankelijk bewijs vergelijkt {left} met {right}?",
                f"Welke beperkingen of incidenten zijn bekend voor {left} en {right}?",
                f"Welke open vragen blijven over {left} vs {right}?",
            ]
        return [
            f"What is the core definition of {left} versus {right}?",
            f"On which dimensions do {left} and {right} differ with evidence?",
            f"What independent evidence compares {left} to {right}?",
            f"What limitations or incidents are documented for {left} and {right}?",
            f"What open questions remain about {left} vs {right}?",
        ]
    if dutchish:
        seeds = [
            f"Wat is vastgesteld over {base}?",
            f"Welke primaire bronnen bestaan over {base}?",
            f"Welk bewijs ondersteunt claims over {base}?",
            f"Welke tegenstrijdige of alternatieve accounts bestaan er over {base}?",
            f"Welke kwantitatieve gegevens zijn beschikbaar over {base}?",
            f"Welke open vragen blijven over {base}?",
        ]
        if objective.strip():
            seeds.insert(1, f"Hoe adresseert het bewijs het doel: {objective.strip()}?")
        return seeds
    seeds = [
        f"What is established about {base}?",
        f"What primary sources exist for {base}?",
        f"What evidence supports claims related to {base}?",
        f"What contradictory or alternative accounts exist for {base}?",
        f"What quantitative data is available about {base}?",
        f"What open questions remain about {base}?",
    ]
    if objective.strip():
        seeds.insert(1, f"How does evidence address the objective: {objective.strip()}?")
    return seeds


def build_question_model(
    project: ResearchProject,
    *,
    enricher: Callable[[ResearchQuestionModel], ResearchQuestionModel] | None = None,
) -> ResearchQuestionModel:
    """Build a deterministic ResearchQuestionModel; optional enricher hook for semantics."""
    topic = (project.topic or "").strip()
    objective = (project.objective or "").strip()
    combined = f"{topic} {objective}".strip()
    dutchish = bool(
        re.search(
            r"\b(de|het|een|wat|hoe|waarom|onderzoek|bewijs|bronnen|tegenstrijdig|vergelijk)\b",
            combined,
            re.I,
        )
    )

    left, right = _detect_comparison(combined)
    entities = _extract_entities(combined)
    if left and left not in entities:
        entities.insert(0, left)
    if right and right not in entities:
        entities.insert(1 if left else 0, right)

    freshness = _freshness_requirement(combined)
    temporal = _temporal_scope(combined)
    geographic = _geographic_scope(combined)

    ambiguities: list[str] = []
    if left and right:
        ambiguities.append(f"Comparison operands detected ({left} vs {right}); dimensions may need operator confirmation")
    if not entities:
        ambiguities.append("No clear named entities extracted; queries stay topic-level")
    if freshness == "none" and re.search(r"\b(status|state of|stand van)\b", combined, re.I):
        ambiguities.append("Status-oriented question without explicit freshness requirement")

    definitions: list[str] = []
    for ent in entities[:5]:
        definitions.append(f"Define '{ent}' as used in this research scope")

    claim_targets = [f"Key factual claims about {ent}" for ent in entities[:5]]
    if left and right:
        claim_targets.append(f"Comparative claims: {left} vs {right}")
    if not claim_targets:
        claim_targets = [f"Key factual claims about {topic}"]

    evidence_requirements = [
        "At least one resolving citation per material factual claim",
        "Preserve contradictory evidence rather than dropping it",
        "Prefer independent corroboration across source clusters",
    ]
    if freshness in {"preferred", "required"}:
        evidence_requirements.append("Include recent sources matching freshness requirement")
    if left and right:
        evidence_requirements.append("Cover both sides of the comparison with comparable evidence")

    source_preferences = ["knowledge", "official_primary", "peer_reviewed", "technical_docs"]
    if project.allow_web:
        source_preferences.append("web_page")
    if project.seed_sources:
        source_preferences.append("seed")

    exclusions = [
        "Do not fabricate sources or citations",
        "Do not silently resolve contradictions",
        "Do not treat marketing copy as primary evidence",
    ]

    assumptions = [
        "Local KnowledgeStore retrieval is authoritative for offline research",
        "Citations must resolve to stored evidence spans",
    ]
    if not project.allow_web:
        assumptions.append("Web discovery is disabled for this project")
    else:
        assumptions.append("Web discovery runs only when a provider is configured")

    scope = "local_knowledge" if not project.allow_web else "local_knowledge+web_when_available"
    if geographic:
        scope = f"{scope}; geo={geographic}"
    if temporal:
        scope = f"{scope}; temporal={temporal}"

    interpreted = topic
    if left and right:
        # Avoid "Compare X and Y: X vs Y …" duplication when topic already compares.
        if re.search(r"\b(vs\.?|versus|vergelijk)\b", topic, re.I):
            interpreted = topic
        else:
            interpreted = f"Compare {left} and {right}: {topic}"
    if objective and objective.lower() not in interpreted.lower():
        interpreted = f"{interpreted} (objective: {objective})" if interpreted else objective

    subquestions = _subquestions_for(topic, objective, left=left, right=right, dutchish=dutchish)
    comparison_dims = _comparison_dimensions(left, right) if left and right else []
    query_portfolio = _build_query_portfolio(
        topic,
        entities,
        left=left,
        right=right,
        freshness=freshness,
    )

    stopping = [
        "Critical and high gaps resolved or explicitly documented",
        "Material claims cited with resolving evidence",
        "Contradictions preserved with conflict records",
    ]
    if freshness == "required":
        stopping.append("Freshness requirement satisfied with dated sources")
    if left and right:
        stopping.append("Both comparison sides covered on core dimensions")

    model = ResearchQuestionModel(
        original_question=topic,
        interpreted_question=interpreted.strip() or topic,
        objective=objective,
        scope=scope,
        entities=entities,
        definitions=definitions,
        temporal_scope=temporal,
        geographic_scope=geographic,
        assumptions=assumptions,
        ambiguities=ambiguities,
        subquestions=subquestions,
        claim_targets=claim_targets,
        evidence_requirements=evidence_requirements,
        source_preferences=_dedupe(source_preferences),
        exclusions=exclusions,
        freshness_requirement=freshness,
        stopping_criteria=stopping,
        comparison_dimensions=comparison_dims,
        query_portfolio=query_portfolio,
    )
    if enricher is not None:
        try:
            enriched = enricher(model)
            if isinstance(enriched, ResearchQuestionModel):
                return enriched
        except Exception:
            # Deterministic core must survive enrichment failures.
            return model
    return model
