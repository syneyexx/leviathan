"""Research evidence conflict presentation — never silently resolve contradictions.

Rules:
- Multiple websites repeating the same origin do not count as independent evidence.
- A citation does not prove the source supports the claim.
- Facts / interpretations / recommendations must stay distinguishable.
- Missing info → explicit knowledge gap.
- Conflicting sources stay visible; no invented confidence percentages.
"""

from __future__ import annotations

from typing import Any

from claim_register import CONTRADICTED, PARTIALLY_SUPPORTED, UNVERIFIED, normalize_verification_status


def _origin_key(evidence: dict[str, Any]) -> str:
    """Collapse republished copies onto a shared origin when declared."""
    return str(
        evidence.get("origin_id")
        or evidence.get("canonical_url")
        or evidence.get("source_url")
        or evidence.get("url")
        or evidence.get("evidence_id")
        or evidence.get("id")
        or ""
    ).strip().lower()


def independent_evidence_count(evidence_links: list[dict[str, Any]]) -> dict[str, Any]:
    """Count independent supporting origins (not republishes of the same source)."""
    origins: set[str] = set()
    republish_of: list[str] = []
    for link in evidence_links or []:
        if str(link.get("relation") or "supports").lower() not in {"supports", "support"}:
            continue
        origin = _origin_key(link)
        parent = str(link.get("republication_of") or link.get("derived_from") or "").strip().lower()
        if parent:
            republish_of.append(origin or parent)
            origins.add(parent)
            continue
        if origin:
            origins.add(origin)
    return {
        "independent_support_origins": len(origins),
        "origins": sorted(origins),
        "republications_collapsed": len(republish_of),
        "note": "Republications of the same origin do not increase independent evidence.",
    }


def classify_statement(kind: str | None) -> str:
    value = str(kind or "fact").strip().lower()
    if value in {"fact", "interpretation", "recommendation", "gap"}:
        return value
    if value in {"claim", "finding"}:
        return "fact"
    if value in {"opinion", "analysis"}:
        return "interpretation"
    if value in {"advice", "action"}:
        return "recommendation"
    if value in {"unknown", "missing", "knowledge_gap"}:
        return "gap"
    return "fact"


def present_claim_with_evidence(claim: dict[str, Any]) -> dict[str, Any]:
    """Normalize a claim into a UI/API-safe evidence card."""
    evidence = list(claim.get("evidence") or claim.get("evidence_links") or [])
    supports = [e for e in evidence if str(e.get("relation") or "").lower() in {"supports", "support", ""}]
    contradicts = [e for e in evidence if str(e.get("relation") or "").lower() in {"contradicts", "contradict"}]
    independence = independent_evidence_count(supports)
    status = normalize_verification_status(claim.get("verification_status") or claim.get("status"))
    statement_kind = classify_statement(claim.get("statement_kind") or claim.get("kind"))
    gaps = list(claim.get("knowledge_gaps") or [])
    if status == UNVERIFIED and not supports and not contradicts:
        gaps = gaps or ["No supporting or contradicting evidence attached."]
    return {
        "claim_id": claim.get("id") or claim.get("claim_id"),
        "text": claim.get("text") or claim.get("claim") or claim.get("title"),
        "statement_kind": statement_kind,
        "verification_status": status,
        "supports": [_evidence_ref(e) for e in supports],
        "contradicts": [_evidence_ref(e) for e in contradicts],
        "independence": independence,
        "knowledge_gaps": gaps,
        "conflicts": [
            {
                "support_ref": _evidence_ref(s),
                "contradict_ref": _evidence_ref(c),
            }
            for s in supports[:3]
            for c in contradicts[:3]
        ],
        "resolved": False if contradicts else None,
        "note": (
            "Conflicting sources are shown; HADES does not invent a resolution."
            if contradicts
            else None
        ),
    }


def _evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": item.get("evidence_id") or item.get("id"),
        "source": item.get("source") or item.get("title") or item.get("source_url") or item.get("url"),
        "passage": item.get("passage") or item.get("excerpt") or item.get("quote"),
        "source_version": item.get("source_version") or item.get("source_hash") or item.get("version"),
        "consulted_at": item.get("consulted_at") or item.get("retrieved_at") or item.get("created_at"),
        "origin_id": _origin_key(item) or None,
        "republication_of": item.get("republication_of") or item.get("derived_from"),
        "relation": item.get("relation"),
    }


def build_conflict_report(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate conflict report for a research task — fixtures or live claims."""
    cards = [present_claim_with_evidence(c) for c in claims or []]
    contradicted = [c for c in cards if c.get("verification_status") == CONTRADICTED or c.get("conflicts")]
    partial = [c for c in cards if c.get("verification_status") == PARTIALLY_SUPPORTED]
    gaps = []
    for card in cards:
        for gap in card.get("knowledge_gaps") or []:
            gaps.append({"claim_id": card.get("claim_id"), "gap": gap})
    return {
        "report_version": "research_conflict_v1",
        "claim_count": len(cards),
        "conflict_count": len(contradicted),
        "partial_count": len(partial),
        "claims": cards,
        "conflicts": contradicted,
        "knowledge_gaps": gaps,
        "silenced": False,
        "invented_resolution": False,
        "reliability_note": (
            "Source weight may use explainable traits (primary vs secondary, dated vs undated); "
            "no fabricated objective reliability percentages."
        ),
    }


def fixture_conflicting_research() -> dict[str, Any]:
    """Deterministic conflicting fixtures for acceptance tests / demos."""
    claims = [
        {
            "id": "claim_fix_alpha",
            "text": "Component X requires cooling below 40C.",
            "statement_kind": "fact",
            "verification_status": CONTRADICTED,
            "evidence": [
                {
                    "id": "ev_manual_a",
                    "source": "Vendor Manual A §3.2",
                    "passage": "Operate below 40C continuous.",
                    "source_version": "manual-a-v2",
                    "consulted_at": "2026-09-01T00:00:00Z",
                    "relation": "supports",
                    "origin_id": "vendor-manual-a",
                },
                {
                    "id": "ev_blog_repost",
                    "source": "Blog repost of Manual A",
                    "passage": "Operate below 40C continuous.",
                    "source_version": "blog-2024",
                    "consulted_at": "2026-09-02T00:00:00Z",
                    "relation": "supports",
                    "republication_of": "vendor-manual-a",
                    "origin_id": "blog-repost",
                },
                {
                    "id": "ev_manual_b",
                    "source": "Vendor Manual B §4.1",
                    "passage": "Rated for continuous operation up to 70C.",
                    "source_version": "manual-b-v1",
                    "consulted_at": "2026-09-01T00:00:00Z",
                    "relation": "contradicts",
                    "origin_id": "vendor-manual-b",
                },
            ],
        },
        {
            "id": "claim_gap_beta",
            "text": "Warranty covers thermal damage abroad.",
            "statement_kind": "fact",
            "verification_status": UNVERIFIED,
            "evidence": [],
            "knowledge_gaps": ["No warranty document available in local fixtures."],
        },
    ]
    report = build_conflict_report(claims)
    # Sanity: independence collapses blog repost.
    independence = report["claims"][0]["independence"]
    assert independence["independent_support_origins"] == 1
    assert independence["republications_collapsed"] == 1
    assert report["silenced"] is False
    assert report["invented_resolution"] is False
    return report
