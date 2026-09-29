"""Canonical claim–evidence relation vocabulary (Wave 10–11).

Relations are first-class graph edges — not free-form LLM labels.
Independent verification must use this vocabulary; model prose is not proof.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ClaimRelation(str, Enum):
    """How a piece of evidence relates to a claim."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    QUALIFIES = "QUALIFIES"
    BACKGROUND = "BACKGROUND"
    INSUFFICIENT = "INSUFFICIENT"


# Legacy lowercase edges from earlier graph builders map into the vocabulary.
_LEGACY_ALIASES: dict[str, ClaimRelation] = {
    "supports": ClaimRelation.SUPPORTS,
    "support": ClaimRelation.SUPPORTS,
    "supported": ClaimRelation.SUPPORTS,
    "contradicts": ClaimRelation.CONTRADICTS,
    "contradict": ClaimRelation.CONTRADICTS,
    "contradicted": ClaimRelation.CONTRADICTS,
    "related": ClaimRelation.BACKGROUND,
    "background": ClaimRelation.BACKGROUND,
    "qualifies": ClaimRelation.QUALIFIES,
    "qualify": ClaimRelation.QUALIFIES,
    "insufficient": ClaimRelation.INSUFFICIENT,
    "insufficient_evidence": ClaimRelation.INSUFFICIENT,
}


def normalize_claim_relation(raw: str | ClaimRelation | None) -> ClaimRelation:
    """Normalize free-form / legacy relation strings into ClaimRelation."""
    if isinstance(raw, ClaimRelation):
        return raw
    text = str(raw or "").strip()
    if not text:
        return ClaimRelation.INSUFFICIENT
    upper = text.upper().replace(" ", "_").replace("-", "_")
    try:
        return ClaimRelation(upper)
    except ValueError:
        pass
    legacy = _LEGACY_ALIASES.get(text.lower())
    if legacy is not None:
        return legacy
    return ClaimRelation.INSUFFICIENT


def relation_from_entailment_status(status: str | None) -> ClaimRelation:
    """Map citation_entailment_check status → ClaimRelation."""
    key = str(status or "").strip().upper()
    if key in {"SUPPORTED", "SUPPORTS"}:
        return ClaimRelation.SUPPORTS
    if key in {"CONTRADICTED", "CONTRADICTS"}:
        return ClaimRelation.CONTRADICTS
    if key in {"QUALIFIES", "QUALIFIED"}:
        return ClaimRelation.QUALIFIES
    if key in {"BACKGROUND", "RELATED"}:
        return ClaimRelation.BACKGROUND
    return ClaimRelation.INSUFFICIENT


def relation_public_dict(relation: ClaimRelation | str) -> dict[str, Any]:
    rel = normalize_claim_relation(relation)
    return {
        "relation": rel.value,
        "truth": {
            "model_prose_is_not_relation_proof": True,
            "vocabulary_is_closed": True,
            "allowed": [r.value for r in ClaimRelation],
        },
    }
