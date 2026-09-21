"""Pillar 4 — Autonomous Concept Formation / Ontology Evolution.

Candidate concepts from repeated verified experiences only.
No unconstrained LLM vocabulary mutation of production ontology.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import AdaptiveDecision, new_id, utc_now
from .modes import CognitiveMode, mode_allows_influence


_WORD = re.compile(r"[a-z0-9_]{3,}", re.I)

ALLOWED_RELATIONS = frozenset(
    {
        "is_a",
        "part_of",
        "causes",
        "correlates_with",
        "contradicts",
        "supersedes",
        "often_cooccurs_with",
    }
)

# Causal relations require causal evidence tier — not mere co-occurrence.
CAUSAL_RELATIONS = frozenset({"causes"})


def _normalize_name(name: str) -> str:
    tokens = _WORD.findall(str(name or "").lower().replace("-", "_").replace(" ", "_"))
    return "_".join(tokens)[:80]


def find_existing_concept(store: Any, name: str, definition: str = "") -> dict[str, Any] | None:
    """Avoid synonym explosion — reuse if name or token-overlap matches."""
    if store is None:
        return None
    normalized = _normalize_name(name)
    existing = store.get_concept_by_name(normalized)
    if existing:
        return existing
    # Soft match against promoted/approved concepts
    def_tokens = set(_WORD.findall(definition.lower())) if definition else set()
    name_tokens = set(normalized.split("_"))
    for concept in store.list_concepts(limit=200):
        if concept.get("status") not in {"approved", "promoted", "candidate"}:
            continue
        other = set(str(concept.get("name") or "").split("_"))
        overlap = len(name_tokens & other) / max(1, len(name_tokens | other))
        if overlap >= 0.75:
            return concept
        if def_tokens:
            other_def = set(_WORD.findall(str(concept.get("definition") or "").lower()))
            def_overlap = len(def_tokens & other_def) / max(1, len(def_tokens | other_def))
            if def_overlap >= 0.8 and len(def_tokens) >= 3:
                return concept
    return None


def propose_concept(
    store: Any,
    *,
    name: str,
    definition: str,
    supporting_examples: list[Any],
    counterexamples: list[Any] | None = None,
    relations: list[dict[str, Any]] | None = None,
    scope: str = "general",
    mode: CognitiveMode = CognitiveMode.SHADOW,
    min_examples: int = 2,
) -> dict[str, Any]:
    """Form a candidate concept only from repeated verified observations."""
    normalized = _normalize_name(name)
    examples = list(supporting_examples or [])
    counters = list(counterexamples or [])
    rels: list[dict[str, Any]] = []
    rejected_relations: list[dict[str, Any]] = []

    for rel in relations or []:
        kind = str(rel.get("relation") or rel.get("type") or "").lower()
        if kind not in ALLOWED_RELATIONS:
            rejected_relations.append({**rel, "reject_reason": "unknown_relation"})
            continue
        if kind in CAUSAL_RELATIONS:
            tier = str(rel.get("causal_evidence_level") or "")
            if tier not in {"intervened", "verified_cause", "counterfactual"}:
                rejected_relations.append({**rel, "reject_reason": "causal_evidence_insufficient"})
                continue
        rels.append({"relation": kind, "target": rel.get("target"), "evidence": rel.get("evidence")})

    existing = find_existing_concept(store, normalized, definition)
    if existing:
        decision = AdaptiveDecision(
            controller="cognitive.ontology",
            decision="reuse_existing",
            reason_code="CONCEPT_ALREADY_EXISTS",
            mode=mode.value,
            input_refs=[existing.get("id", "")],
        )
        return {
            "status": "reused",
            "concept": existing,
            "decision": decision.to_dict(),
            "rejected_relations": rejected_relations,
        }

    if len(examples) < min_examples:
        decision = AdaptiveDecision(
            controller="cognitive.ontology",
            decision="reject_noise",
            reason_code="INSUFFICIENT_VERIFIED_EXAMPLES",
            mode=mode.value,
        )
        return {
            "status": "rejected",
            "reason": "need_repeated_verified_observations",
            "required_examples": min_examples,
            "got_examples": len(examples),
            "decision": decision.to_dict(),
            "rejected_relations": rejected_relations,
        }

    confidence = min(0.95, 0.4 + 0.15 * len(examples) - 0.1 * len(counters))
    concept = {
        "id": new_id("concept"),
        "name": normalized,
        "definition": definition.strip(),
        "status": "candidate",
        "confidence": round(confidence, 3),
        "scope": scope,
        "version": 1,
        "supporting_examples": examples,
        "counterexamples": counters,
        "relations": rels,
        "created_at": utc_now(),
    }

    influence = mode_allows_influence(mode)
    if influence and store is not None:
        concept = store.upsert_concept(concept)

    decision = AdaptiveDecision(
        controller="cognitive.ontology",
        decision="candidate_created" if influence else "candidate_shadow",
        reason_code="REPEATED_VERIFIED_EXPERIENCE",
        mode=mode.value,
        confidence=confidence,
    )
    return {
        "status": "candidate" if influence else "shadow_candidate",
        "concept": concept,
        "decision": decision.to_dict(),
        "rejected_relations": rejected_relations,
    }


def evaluate_and_promote(
    store: Any,
    *,
    name: str,
    human_approved: bool = False,
    min_examples: int = 3,
    mode: CognitiveMode = CognitiveMode.SHADOW,
) -> dict[str, Any]:
    """Promote only with sufficient evidence + explicit approval gate for production ontology."""
    concept = store.get_concept_by_name(_normalize_name(name)) if store else None
    if not concept:
        return {"status": "missing", "promoted": False}
    evidence = list(concept.get("evidence") or [])
    if len(evidence) < min_examples:
        return {
            "status": "held",
            "promoted": False,
            "reason": "insufficient_evidence",
            "concept": concept,
        }
    if not human_approved and mode is not CognitiveMode.ACTIVE:
        return {
            "status": "awaits_approval",
            "promoted": False,
            "concept": concept,
            "decision": AdaptiveDecision(
                controller="cognitive.ontology",
                decision="hold",
                reason_code="APPROVAL_REQUIRED",
                mode=mode.value,
            ).to_dict(),
        }
    if not human_approved:
        # ACTIVE still requires approval for production ontology mutation
        return {
            "status": "awaits_approval",
            "promoted": False,
            "reason": "production_ontology_requires_approval",
            "concept": concept,
        }
    updated = store.upsert_concept(
        {
            "name": concept["name"],
            "definition": concept["definition"],
            "status": "promoted",
            "confidence": concept.get("confidence"),
            "scope": concept.get("scope"),
            "supporting_examples": evidence,
            "relations": concept.get("relations") or [],
            "promote": True,
        }
    )
    return {
        "status": "promoted",
        "promoted": True,
        "concept": updated,
        "decision": AdaptiveDecision(
            controller="cognitive.ontology",
            decision="promote",
            reason_code="APPROVED_WITH_EVIDENCE",
            mode=mode.value,
            confidence=updated.get("confidence"),
        ).to_dict(),
    }
