"""Contradiction handling — never silently resolve conflicting evidence."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from .store import ResearchStore
from .types import ClaimStatus, ResearchClaim, ResearchConflict, ResearchEvidence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_NUMBER = re.compile(r"\b(\d+(?:\.\d+)?)\b")
_POPULATION_HINT = re.compile(
    r"\b(population|sample|cohort|n\s*=|respondents|users|patients|participants)\b",
    re.I,
)
_METRIC_HINT = re.compile(
    r"\b(percent|percentage|rate|ratio|mean|median|latency|throughput|accuracy|score|usd|eur|\$|%)\b",
    re.I,
)
_SCOPE_HINT = re.compile(
    r"\b(in|for|among|within|only|excluding|except|globally|nationwide|eu|us|uk)\b",
    re.I,
)


def _years_from_text(text: str) -> set[str]:
    return set(_YEAR.findall(text or ""))


def _numbers_from_text(text: str) -> set[str]:
    return set(_NUMBER.findall(text or ""))


def _classify_conflict_kind(
    claim: ResearchClaim,
    support_spans: list[str],
    contradict_spans: list[str],
) -> tuple[str, list[str]]:
    """Return (conflict_kind, reconciliation_hints) without choosing a winner."""
    hints: list[str] = []
    meta_years = claim.metadata.get("years") if isinstance(claim.metadata, dict) else None
    years_support: set[str] = set()
    years_contra: set[str] = set()
    for span in support_spans:
        years_support |= _years_from_text(span)
    for span in contradict_spans:
        years_contra |= _years_from_text(span)
    all_years = set(meta_years or []) | years_support | years_contra

    nums_support: set[str] = set()
    nums_contra: set[str] = set()
    for span in support_spans:
        nums_support |= _numbers_from_text(span)
    for span in contradict_spans:
        nums_contra |= _numbers_from_text(span)

    support_blob = " ".join(support_spans)
    contra_blob = " ".join(contradict_spans)

    # Temporal disagreement: different years, otherwise overlapping content.
    if len(all_years) > 1 or (years_support and years_contra and years_support != years_contra):
        hints.append(
            f"Sources cite different years ({', '.join(sorted(all_years))}); "
            "they may describe distinct events or revisions rather than a single fact."
        )
        return "temporal_disagreement", hints

    # Scope mismatch: population / geography / qualifier cues differ.
    pop_s = bool(_POPULATION_HINT.search(support_blob))
    pop_c = bool(_POPULATION_HINT.search(contra_blob))
    scope_s = bool(_SCOPE_HINT.search(support_blob))
    scope_c = bool(_SCOPE_HINT.search(contra_blob))
    if (pop_s or pop_c) and (nums_support != nums_contra or pop_s != pop_c):
        hints.append(
            "Numeric or population framing differs; check whether samples/cohorts are comparable."
        )
        return "scope_mismatch", hints
    if scope_s and scope_c and nums_support and nums_contra and nums_support.isdisjoint(nums_contra):
        hints.append(
            "Scope qualifiers differ alongside mismatched numbers; "
            "accounts may apply to different regions or subsets."
        )
        return "scope_mismatch", hints

    # Metric mismatch without clear temporal split.
    metric_s = bool(_METRIC_HINT.search(support_blob))
    metric_c = bool(_METRIC_HINT.search(contra_blob))
    if (metric_s or metric_c) and nums_support and nums_contra and nums_support.isdisjoint(nums_contra):
        hints.append(
            "Different metrics or units may be in play; align definitions before treating as contradiction."
        )
        return "apparent_contradiction", hints

    # Negation polarity / direct clash.
    neg = re.compile(
        r"\b(does not|do not|don't|doesn't|did not|didn't|never|no longer|"
        r"cannot|can't|is not|are not|isn't|aren't|was not|weren't|not)\b",
        re.I,
    )
    if bool(neg.search(support_blob)) != bool(neg.search(contra_blob)):
        hints.append(
            "Polarity differs (affirmation vs negation) on overlapping content; "
            "verify definitions and measurement windows."
        )
        return "direct_contradiction", hints

    if nums_support and nums_contra and nums_support.isdisjoint(nums_contra):
        hints.append(
            "Conflicting numeric values without a clear year split; "
            "confirm whether the same metric and population are compared."
        )
        return "apparent_contradiction", hints

    hints.append(
        "Supporting and contradicting spans disagree; preserve both pending better primary evidence."
    )
    return "apparent_contradiction", hints


class ConflictDetector:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def _spans_for(self, evidence_ids: list[str]) -> list[str]:
        spans: list[str] = []
        for eid in evidence_ids:
            ev: ResearchEvidence | None = self.store.get_evidence(eid)
            if ev is not None and ev.span_text:
                spans.append(ev.span_text)
        return spans

    def detect(self, project_id: str, claims: list[ResearchClaim] | None = None) -> list[ResearchConflict]:
        claims = claims if claims is not None else self.store.list_claims(project_id)
        existing = self.store.list_conflicts(project_id)
        existing_keys = {
            (
                c.claim_id,
                tuple(c.supporting_evidence_ids),
                tuple(c.contradicting_evidence_ids),
            )
            for c in existing
        }
        out: list[ResearchConflict] = []
        for claim in claims:
            if claim.status != ClaimStatus.DISPUTED and not claim.contradicting_evidence_ids:
                continue
            if not claim.contradicting_evidence_ids:
                continue
            key = (
                claim.claim_id,
                tuple(claim.supporting_evidence_ids),
                tuple(claim.contradicting_evidence_ids),
            )
            if key in existing_keys:
                continue
            years = claim.metadata.get("years") if isinstance(claim.metadata, dict) else None
            support_spans = self._spans_for(list(claim.supporting_evidence_ids))
            contradict_spans = self._spans_for(list(claim.contradicting_evidence_ids))
            conflict_kind, reconciliation_hints = _classify_conflict_kind(
                claim, support_spans, contradict_spans
            )

            if conflict_kind == "temporal_disagreement" and years:
                summary = (
                    f"Sources disagree on timing ({', '.join(str(y) for y in years)}): "
                    f"{claim.proposition}"
                )
            elif conflict_kind == "scope_mismatch":
                summary = f"Possible scope mismatch for claim: {claim.proposition}"
            elif conflict_kind == "direct_contradiction":
                summary = f"Direct contradiction for claim: {claim.proposition}"
            else:
                summary = f"Apparent contradiction for claim: {claim.proposition}"

            conflict = ResearchConflict(
                conflict_id=str(uuid.uuid4()),
                project_id=project_id,
                claim_id=claim.claim_id,
                summary=summary,
                supporting_evidence_ids=list(claim.supporting_evidence_ids),
                contradicting_evidence_ids=list(claim.contradicting_evidence_ids),
                analysis={
                    "policy": "preserve_both",
                    "resolution": "unresolved",
                    "conflict_kind": conflict_kind,
                    "years": years or [],
                    "reconciliation_hints": reconciliation_hints,
                    "note": (
                        "Both supporting and contradicting evidence are retained. "
                        "Report must express uncertainty rather than picking a side. "
                        "Hints suggest possible reconciliation axes only — not a verdict."
                    ),
                },
                unresolved_questions=[
                    f"Which account of the following is correct, and under what definition: {claim.proposition}?"
                ],
                created_at=utc_now(),
            )
            self.store.add_conflict(conflict)
            out.append(conflict)
        return out
