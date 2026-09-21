"""Claim/evidence coverage distinct from mere reference existence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SupportLevel = Literal[
    "direct_observation",
    "source_passage",
    "model_interpretation",
    "insufficient",
    "contradicted",
]

EvidenceKind = Literal[
    "source_material",
    "tool_observation",
    "deterministic_check",
    "model_interpretation",
    "draft_under_review",
    "unknown",
]


@dataclass(slots=True)
class EvidenceItem:
    """Explicit provenance for one evidence artifact."""

    ref: str
    kind: EvidenceKind
    provenance: str
    content: str = ""
    observes: list[str] = field(default_factory=list)  # what the tool/check actually showed
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ClaimRecord:
    claim_id: str
    text: str
    support_level: SupportLevel
    evidence_refs: list[str] = field(default_factory=list)
    source_versions: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    quote_verified: bool | None = None
    evidence_kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CoverageReport:
    claims: list[ClaimRecord]
    sufficient: bool
    missing_refs: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    factual_verified: bool = False
    verification_label: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "sufficient": self.sufficient,
            "missing_refs": list(self.missing_refs),
            "contradictions": list(self.contradictions),
            "notes": list(self.notes),
            "factual_verified": self.factual_verified,
            "verification_label": self.verification_label,
        }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


_TOOL_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}
_TOOL_TOKEN_ALIASES = {
    "ok": "success",
    "okay": "success",
    "pass": "success",
    "passed": "success",
    "passes": "success",
    "passing": "success",
    "success": "success",
    "successful": "success",
    "successfully": "success",
    "succeed": "success",
    "succeeded": "success",
    "succeeds": "success",
    "complete": "success",
    "completed": "success",
    "completion": "success",
    "fail": "failure",
    "failed": "failure",
    "fails": "failure",
    "failing": "failure",
    "failure": "failure",
    "error": "failure",
    "errored": "failure",
}


def _tool_alignment_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-zA-Z0-9à-ÿ]{2,}", normalize_text(value)):
        token = raw
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
            token = token[:-1]
        token = _TOOL_TOKEN_ALIASES.get(token, token)
        if token not in _TOOL_STOP_WORDS:
            tokens.add(token)
    return tokens


def tool_observation_supports_claim(claim_text: str, evidence_text: str) -> bool:
    """Conservatively require a tool/check output to align with the claim it proves.

    Tool outputs are often terse (``test_add ... ok``) while claims are prose
    (``Tests passed for add()``), so literal quote matching alone is too strict.
    Normalize common success/failure words and simple plurals, then require at
    least two meaningful shared tokens. A successful but unrelated tool call is
    never sufficient evidence merely because its ref exists.
    """
    if not claim_text.strip() or not evidence_text.strip():
        return False
    if quote_in_source(claim_text[:200], evidence_text):
        return True
    claim_tokens = _tool_alignment_tokens(claim_text)
    evidence_tokens = _tool_alignment_tokens(evidence_text)
    return len(claim_tokens & evidence_tokens) >= 2


def stable_claim_id(text: str, *, namespace: str = "claim") -> str:
    """Process-stable claim identity (not Python hash())."""
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]
    return f"{namespace}_{digest}"


def quote_in_source(quote: str, source_text: str) -> bool:
    q = normalize_text(quote)
    if len(q) < 12:
        return False
    return q in normalize_text(source_text)


def classify_evidence_item(raw: dict[str, Any]) -> EvidenceItem:
    ref = str(raw.get("ref") or raw.get("evidence_ref") or raw.get("id") or "").strip()
    kind_raw = str(raw.get("kind") or raw.get("evidence_kind") or "").strip().lower()
    role = str(raw.get("evidence_role") or raw.get("role") or "").strip().lower()
    if role in {"draft", "candidate_answer", "under_review"} or raw.get("is_draft"):
        kind: EvidenceKind = "draft_under_review"
    elif kind_raw in {"source_material", "source", "passage", "document"}:
        kind = "source_material"
    elif kind_raw in {"tool_observation", "tool", "observation"} or raw.get("is_tool_observation"):
        kind = "tool_observation"
    elif kind_raw in {"deterministic_check", "check", "calculation", "unit_test"}:
        kind = "deterministic_check"
    elif kind_raw in {"model_interpretation", "interpretation", "inference"}:
        kind = "model_interpretation"
    else:
        kind = "unknown"
    observes = [str(item) for item in (raw.get("observes") or raw.get("observed") or [])]
    return EvidenceItem(
        ref=ref,
        kind=kind,
        provenance=str(raw.get("provenance") or raw.get("source") or ref),
        content=str(raw.get("content") or raw.get("text") or raw.get("output") or ""),
        observes=observes,
        notes=[str(item) for item in (raw.get("notes") or [])],
    )


def classify_support(
    *,
    claim_text: str,
    evidence_texts: dict[str, str],
    evidence_refs: list[str],
    known_refs: set[str],
    is_tool_observation: bool = False,
    contradicting_refs: list[str] | None = None,
    evidence_kinds: dict[str, EvidenceKind] | None = None,
) -> ClaimRecord:
    """Deterministic layer: existence + optional quote check. Semantic fit is separate."""
    evidence_kinds = evidence_kinds or {}
    missing = [ref for ref in evidence_refs if ref not in known_refs]
    notes: list[str] = []
    claim_id = stable_claim_id(claim_text)
    kinds_used = [evidence_kinds.get(ref, "unknown") for ref in evidence_refs]

    if any(evidence_kinds.get(ref) == "draft_under_review" for ref in evidence_refs):
        notes.append("circular_draft_reference_rejected")
        return ClaimRecord(
            claim_id=claim_id,
            text=claim_text[:500],
            support_level="insufficient",
            evidence_refs=list(evidence_refs),
            notes=notes,
            evidence_kinds=[str(k) for k in kinds_used],
        )

    if missing:
        notes.append("missing_evidence_refs")
        return ClaimRecord(
            claim_id=claim_id,
            text=claim_text[:500],
            support_level="insufficient",
            evidence_refs=list(evidence_refs),
            notes=notes + [f"missing:{ref}" for ref in missing],
            evidence_kinds=[str(k) for k in kinds_used],
        )

    if contradicting_refs:
        return ClaimRecord(
            claim_id=claim_id,
            text=claim_text[:500],
            support_level="contradicted",
            evidence_refs=list(evidence_refs),
            notes=["contradicted_by:" + ",".join(contradicting_refs)],
            evidence_kinds=[str(k) for k in kinds_used],
        )

    # A successful tool call only proves what its content actually shows.
    if is_tool_observation and evidence_refs:
        tool_kinds = [evidence_kinds.get(ref, "tool_observation") for ref in evidence_refs]
        if all(k in {"tool_observation", "deterministic_check"} for k in tool_kinds):
            aligned_refs = [
                ref
                for ref in evidence_refs
                if tool_observation_supports_claim(claim_text, evidence_texts.get(ref) or "")
            ]
            if aligned_refs:
                return ClaimRecord(
                    claim_id=claim_id,
                    text=claim_text[:500],
                    support_level="direct_observation",
                    evidence_refs=list(evidence_refs),
                    notes=["tool_or_runtime_observation", "content_alignment_verified"],
                    evidence_kinds=[str(k) for k in kinds_used],
                )
            notes.append("tool_observation_content_not_aligned")

    quote_ok: bool | None = None
    matched_passage = False
    for ref in evidence_refs:
        if evidence_kinds.get(ref) == "model_interpretation":
            continue
        text = evidence_texts.get(ref) or ""
        if not text:
            continue
        if len(claim_text) > 40 and quote_in_source(claim_text[:200], text):
            quote_ok = True
            matched_passage = True
            break
        claim_tokens = set(normalize_text(claim_text).split())
        src_tokens = set(normalize_text(text).split())
        if len(claim_tokens & src_tokens) >= 3:
            matched_passage = True

    if matched_passage and (
        quote_ok
        or (
            len(claim_text) >= 24
            and quote_ok is not False
            and any(quote_in_source(claim_text[:200], evidence_texts.get(ref) or "") for ref in evidence_refs)
        )
    ):
        level: SupportLevel = "source_passage"
        notes.append("literal_quote_verified")
        quote_ok = True
    elif matched_passage:
        # Relevant-looking source exists but does not prove the conclusion.
        level = "model_interpretation"
        notes.append("source_present_but_support_not_proven")
    elif evidence_refs:
        level = "insufficient"
        notes.append("refs_exist_but_content_not_aligned")
    else:
        level = "insufficient"
        notes.append("no_evidence")

    return ClaimRecord(
        claim_id=claim_id,
        text=claim_text[:500],
        support_level=level,
        evidence_refs=list(evidence_refs),
        quote_verified=quote_ok,
        notes=notes,
        evidence_kinds=[str(k) for k in kinds_used],
    )


def extract_checkable_claims(answer: str, *, max_claims: int = 8) -> list[str]:
    """Split a long answer into checkable claim-sized units (not one blob)."""
    text = (answer or "").strip()
    if not text:
        return []
    # Prefer sentence-like units; skip tiny fragments.
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    claims: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) < 24:
            continue
        # Skip pure meta / hedging without factual payload.
        lower = cleaned.lower()
        if lower.startswith(("ik denk", "i think", "misschien", "perhaps")) and len(cleaned) < 60:
            continue
        claims.append(cleaned[:500])
        if len(claims) >= max_claims:
            break
    if not claims and len(text) >= 24:
        claims.append(text[:500])
    return claims


def assess_coverage(
    claims: list[dict[str, Any]],
    *,
    known_refs: set[str],
    evidence_texts: dict[str, str] | None = None,
    evidence_kinds: dict[str, EvidenceKind] | None = None,
    require_factual: bool = False,
) -> CoverageReport:
    evidence_texts = evidence_texts or {}
    evidence_kinds = evidence_kinds or {}
    records: list[ClaimRecord] = []
    missing: list[str] = []
    contradictions: list[str] = []
    for index, raw in enumerate(claims):
        text = str(raw.get("text") or raw.get("claim") or "").strip()
        if not text:
            continue
        refs = [str(item) for item in (raw.get("evidence_refs") or [])]
        record = classify_support(
            claim_text=text,
            evidence_texts=evidence_texts,
            evidence_refs=refs,
            known_refs=known_refs,
            is_tool_observation=bool(raw.get("is_tool_observation")),
            contradicting_refs=[str(item) for item in (raw.get("contradicting_refs") or [])],
            evidence_kinds=evidence_kinds,
        )
        if not record.claim_id:
            record.claim_id = stable_claim_id(text) or f"claim_{index}"
        records.append(record)
        for ref in refs:
            if ref not in known_refs:
                missing.append(ref)
        if record.support_level == "contradicted":
            contradictions.append(record.text[:120])

    sufficient = bool(records) and all(
        item.support_level in {"direct_observation", "source_passage"} for item in records
    )
    notes: list[str] = []
    if any(item.support_level == "model_interpretation" for item in records):
        notes.append("model_interpretation_is_not_sufficient_proof")
    if any("circular_draft_reference_rejected" in item.notes for item in records):
        notes.append("draft_cannot_prove_own_claims")
    factual_verified = bool(sufficient and require_factual and not contradictions and not missing)
    if require_factual and not records:
        label = "not_checked"
        notes.append("no_claims_extracted_for_factual_check")
    elif factual_verified:
        label = "factual_verified"
    elif sufficient:
        label = "supported"
    elif any(item.support_level == "contradicted" for item in records):
        label = "contradicted"
    elif records:
        label = "unverified"
    else:
        label = "not_checked"
    return CoverageReport(
        claims=records,
        sufficient=sufficient,
        missing_refs=sorted(set(missing)),
        contradictions=contradictions,
        notes=notes,
        factual_verified=factual_verified,
        verification_label=label,
    )


_QUOTE_RE = re.compile(r"[\"“”«»]([^\"“”«»]{12,400})[\"“”«»]")


def extract_quoted_spans(answer: str, *, max_quotes: int = 12) -> list[str]:
    """Extract explicit quotation spans from an answer for citation checks."""
    found: list[str] = []
    for match in _QUOTE_RE.finditer(answer or ""):
        quote = match.group(1).strip()
        if len(quote) < 12:
            continue
        found.append(quote)
        if len(found) >= max_quotes:
            break
    return found


def verify_quoted_citations(
    answer: str,
    *,
    evidence_texts: dict[str, str] | None,
) -> dict[str, Any]:
    """Mark invented quotes that do not appear in any provided source text (T15).

    Runs on every sourced answer path — not only when the critic is invoked.
    Short quotes (<12 normalized chars) are skipped (same rule as quote_in_source).
    """
    sources = {str(k): str(v or "") for k, v in (evidence_texts or {}).items() if str(v or "").strip()}
    quotes = extract_quoted_spans(answer)
    covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    if not quotes:
        return {
            "checked": False,
            "reason": "no_explicit_quotes",
            "covered": [],
            "uncovered": [],
            "has_invented_citation": False,
        }
    if not sources:
        for quote in quotes:
            uncovered.append({"quote": quote[:240], "reason": "no_sources_available"})
        return {
            "checked": True,
            "reason": "quotes_without_sources",
            "covered": [],
            "uncovered": uncovered,
            "has_invented_citation": bool(uncovered),
        }
    for quote in quotes:
        matched_ref = None
        for ref, text in sources.items():
            if quote_in_source(quote, text):
                matched_ref = ref
                break
        if matched_ref:
            covered.append({"quote": quote[:240], "ref": matched_ref})
        else:
            uncovered.append({"quote": quote[:240], "reason": "quote_not_in_sources"})
    return {
        "checked": True,
        "reason": "ok",
        "covered": covered,
        "uncovered": uncovered,
        "has_invented_citation": bool(uncovered),
    }


def annotate_uncovered_citations(answer: str, citation_report: dict[str, Any]) -> tuple[str, list[str]]:
    """Append an honest note when invented quotes are detected; never invent coverage."""
    notes: list[str] = []
    if not citation_report.get("has_invented_citation"):
        return answer, notes
    uncovered = citation_report.get("uncovered") or []
    notes.append(f"invented_citations:{len(uncovered)}")
    preview = "; ".join(f"“{(row.get('quote') or '')[:60]}…”" for row in uncovered[:3] if isinstance(row, dict))
    marker = (
        "\n\n[HADES citaatcontrole] Een of meer aanhalingstekens in dit antwoord "
        "komen niet voor in de beschikbare bronnen"
        + (f": {preview}" if preview else "")
        + ". Behandel die citaten als ongedekt."
    )
    if marker.strip() in (answer or ""):
        return answer, notes
    return (answer or "") + marker, notes


def apply_citation_verification(
    answer: str,
    *,
    evidence_texts: dict[str, str] | None,
    sources_used: bool,
) -> tuple[str, dict[str, Any], list[str]]:
    """Run citation checks on sourced answers; skip unmarked turns without sources (T15)."""
    if not sources_used:
        report = {
            "checked": False,
            "reason": "no_sources_in_turn",
            "covered": [],
            "uncovered": [],
            "has_invented_citation": False,
        }
        return answer, report, []
    report = verify_quoted_citations(answer, evidence_texts=evidence_texts)
    annotated, notes = annotate_uncovered_citations(answer, report)
    return annotated, report, notes
