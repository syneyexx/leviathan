"""Post-synthesis claim-level citation audit — never invent citations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .evidence import EvidenceLedger
from .store import ResearchStore
from .types import ClaimStatus, ResearchProject


class CitationAuditStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNCITED = "UNCITED"
    CITATION_MISMATCH = "CITATION_MISMATCH"
    INTERPRETATION = "INTERPRETATION"


@dataclass
class CitationAuditItem:
    claim_text: str
    claim_id: str | None
    citation_keys: list[str]
    status: CitationAuditStatus
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "claim_text": self.claim_text,
            "claim_id": self.claim_id,
            "citation_keys": list(self.citation_keys),
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass
class CitationAuditReport:
    items: list[CitationAuditItem] = field(default_factory=list)
    critical_unsupported: list[CitationAuditItem] = field(default_factory=list)
    repair_suggestions: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [i.public_dict() for i in self.items],
            "critical_unsupported": [i.public_dict() for i in self.critical_unsupported],
            "repair_suggestions": list(self.repair_suggestions),
            "summary": {
                "item_count": len(self.items),
                "critical_unsupported_count": len(self.critical_unsupported),
            },
            "truth": {
                "audit_does_not_invent_citations": True,
                "heuristic_entailment_is_not_proof": True,
            },
        }


_CITATION_RE = re.compile(r"\[(e:[0-9a-fA-F-]{8,}|unresolved:[0-9a-fA-F-]{8,})\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_FACTUAL_HINTS = re.compile(
    r"\b(?:is|are|was|were|has|have|had|launched|released|founded|announced|"
    r"increased|decreased|reported|according to|percent|%|\d+)\b",
    re.I,
)
_INTERPRETATION_HINTS = re.compile(
    r"\b(?:suggests?|implies?|appears?|seems?|may|might|could|likely|"
    r"in summary|overall|we conclude|interpretation)\b",
    re.I,
)


def _extract_citations(sentence: str) -> list[str]:
    keys: list[str] = []
    for match in _CITATION_RE.finditer(sentence or ""):
        raw = match.group(1)
        if raw.startswith("unresolved:"):
            keys.append(f"e:{raw.split(':', 1)[1]}")
        else:
            keys.append(raw if raw.startswith("e:") else f"e:{raw}")
    # Preserve order, dedupe.
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _strip_citations(sentence: str) -> str:
    return _CITATION_RE.sub("", sentence or "").strip()


def _looks_factual(sentence: str) -> bool:
    text = _strip_citations(sentence)
    if len(text) < 25:
        return False
    if _INTERPRETATION_HINTS.search(text) and not _YEAR.search(text):
        return False
    return bool(_FACTUAL_HINTS.search(text) or _YEAR.search(text) or re.search(r"\d", text))


def _looks_interpretation(sentence: str) -> bool:
    text = _strip_citations(sentence)
    return bool(_INTERPRETATION_HINTS.search(text)) and not _YEAR.search(text)


def _match_claim_id(store: ResearchStore, project_id: str, sentence: str) -> str | None:
    claims = store.list_claims(project_id)
    text = _strip_citations(sentence).lower()
    tokens = {t for t in re.findall(r"[a-z0-9]{4,}", text)}
    best_id: str | None = None
    best_score = 0.0
    for claim in claims:
        prop_tokens = {t for t in re.findall(r"[a-z0-9]{4,}", (claim.proposition or "").lower())}
        if not prop_tokens or not tokens:
            continue
        overlap = len(tokens & prop_tokens) / float(len(tokens | prop_tokens))
        if overlap > best_score:
            best_score = overlap
            best_id = claim.claim_id
    if best_score >= 0.25:
        return best_id
    return None


def audit_report(
    store: ResearchStore,
    project: ResearchProject,
    report_markdown: str,
) -> CitationAuditReport:
    """Audit claim-level citations in synthesized markdown.

    Never invents citations; only flags mismatches / missing support.
    """
    ledger = EvidenceLedger(store)
    project_id = project.project_id
    claims_by_id = {c.claim_id: c for c in store.list_claims(project_id)}

    try:
        from .graph import citation_entailment_check
    except Exception:  # pragma: no cover - defensive
        citation_entailment_check = None  # type: ignore[assignment]

    items: list[CitationAuditItem] = []
    critical: list[CitationAuditItem] = []
    repairs: list[str] = []

    # Split into sentences while keeping citation markers attached.
    body = report_markdown or ""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(body) if s.strip()]

    for sentence in sentences:
        # Skip headings / list chrome.
        if sentence.startswith("#") or sentence.startswith("---"):
            continue
        citations = _extract_citations(sentence)
        claim_id = _match_claim_id(store, project_id, sentence)
        claim = claims_by_id.get(claim_id) if claim_id else None

        if not citations:
            if _looks_interpretation(sentence):
                items.append(
                    CitationAuditItem(
                        claim_text=_strip_citations(sentence)[:500],
                        claim_id=claim_id,
                        citation_keys=[],
                        status=CitationAuditStatus.INTERPRETATION,
                        reason="Interpretive / hedging language; citation optional",
                    )
                )
                continue
            if _looks_factual(sentence):
                item = CitationAuditItem(
                    claim_text=_strip_citations(sentence)[:500],
                    claim_id=claim_id,
                    citation_keys=[],
                    status=CitationAuditStatus.UNCITED,
                    reason="Factual-looking sentence has no [e:…] citation",
                )
                items.append(item)
                critical.append(item)
                repairs.append(
                    f"Add a resolving evidence citation for: {_strip_citations(sentence)[:120]}"
                )
            continue

        # Resolve each citation via ledger — never invent.
        resolutions = [ledger.resolve_citation(project_id, key) for key in citations]
        unresolved = [r for r in resolutions if not r.resolved]
        if unresolved:
            item = CitationAuditItem(
                claim_text=_strip_citations(sentence)[:500],
                claim_id=claim_id,
                citation_keys=citations,
                status=CitationAuditStatus.CITATION_MISMATCH,
                reason=(
                    "Citation does not resolve to stored evidence/source/snapshot: "
                    + ", ".join(r.reason or "unresolved" for r in unresolved)
                ),
            )
            items.append(item)
            critical.append(item)
            repairs.append(
                f"Replace unresolved citation(s) {citations} with valid evidence keys "
                f"or remove the factual claim"
            )
            continue

        # Entailment check against cited spans when available.
        statuses: list[str] = []
        details: list[str] = []
        for resolution in resolutions:
            span = resolution.span_text or ""
            claim_text = (claim.proposition if claim else _strip_citations(sentence))[:500]
            if citation_entailment_check is not None and span:
                check = citation_entailment_check(claim_text, span)
                statuses.append(str(check.get("status") or "INSUFFICIENT_EVIDENCE"))
                details.append(str(check.get("detail") or ""))
            else:
                statuses.append("INSUFFICIENT_EVIDENCE")
                details.append("entailment unavailable or empty span")

        if claim and claim.status == ClaimStatus.DISPUTED:
            item = CitationAuditItem(
                claim_text=_strip_citations(sentence)[:500],
                claim_id=claim_id,
                citation_keys=citations,
                status=CitationAuditStatus.CONTRADICTED,
                reason="Linked claim is disputed; both sides must remain visible",
            )
            items.append(item)
            continue

        if any(s == "CONTRADICTED" for s in statuses):
            item = CitationAuditItem(
                claim_text=_strip_citations(sentence)[:500],
                claim_id=claim_id,
                citation_keys=citations,
                status=CitationAuditStatus.CONTRADICTED,
                reason="; ".join(d for d in details if d) or "Cited span contradicts claim",
            )
            items.append(item)
            critical.append(item)
            repairs.append(
                f"Review contradiction for claim/sentence: {_strip_citations(sentence)[:120]}"
            )
        elif all(s == "SUPPORTED" for s in statuses):
            items.append(
                CitationAuditItem(
                    claim_text=_strip_citations(sentence)[:500],
                    claim_id=claim_id,
                    citation_keys=citations,
                    status=CitationAuditStatus.SUPPORTED,
                    reason="Citations resolve and heuristically support the sentence",
                )
            )
        elif any(s == "SUPPORTED" for s in statuses):
            items.append(
                CitationAuditItem(
                    claim_text=_strip_citations(sentence)[:500],
                    claim_id=claim_id,
                    citation_keys=citations,
                    status=CitationAuditStatus.PARTIALLY_SUPPORTED,
                    reason="Some citations support; others are weak or insufficient",
                )
            )
        else:
            item = CitationAuditItem(
                claim_text=_strip_citations(sentence)[:500],
                claim_id=claim_id,
                citation_keys=citations,
                status=CitationAuditStatus.CITATION_MISMATCH,
                reason="Citations resolve but do not lexically support the claim text",
            )
            items.append(item)
            repairs.append(
                f"Re-check citation relevance for: {_strip_citations(sentence)[:120]}"
            )

    # Also surface store claims that are unsupported if mentioned nowhere.
    mentioned_claim_ids = {i.claim_id for i in items if i.claim_id}
    for claim in claims_by_id.values():
        if claim.claim_id in mentioned_claim_ids:
            continue
        if claim.status in {ClaimStatus.UNSUPPORTED, ClaimStatus.UNRESOLVED}:
            item = CitationAuditItem(
                claim_text=claim.proposition[:500],
                claim_id=claim.claim_id,
                citation_keys=[],
                status=CitationAuditStatus.UNCITED,
                reason="Store claim remains unsupported and was not cited in the report",
            )
            items.append(item)
            critical.append(item)

    # Deduplicate repair suggestions.
    repairs = list(dict.fromkeys(repairs))
    return CitationAuditReport(
        items=items,
        critical_unsupported=critical,
        repair_suggestions=repairs,
    )
