"""Claim extraction and status assignment from stored evidence (deterministic)."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from .store import ResearchStore
from .types import ClaimStatus, ResearchClaim, ResearchEvidence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_LAUNCH = re.compile(
    r"\b(?:launched|released|introduced|founded|created|announced)\b",
    re.I,
)


def _normalize_proposition(sentence: str) -> str:
    text = re.sub(r"\s+", " ", sentence.strip())
    text = re.sub(r"[\"“”]", "", text)
    # Normalize years to placeholder for grouping conflicting year claims.
    text_no_year = _YEAR.sub("YEAR", text)
    text_no_year = re.sub(r"\s+", " ", text_no_year).strip().lower()
    return text_no_year[:400]


def _candidate_sentences(span: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(span.strip())
    out: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) < 20:
            continue
        # Prefer factual-looking statements.
        if _YEAR.search(cleaned) or _LAUNCH.search(cleaned) or len(cleaned) > 40:
            out.append(cleaned)
    return out[:6]


class ClaimAnalyzer:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def analyze_project(self, project_id: str) -> list[ResearchClaim]:
        evidence = self.store.list_evidence(project_id)
        # Group by normalized proposition (year-agnostic when year present).
        groups: dict[str, list[tuple[ResearchEvidence, str, str | None]]] = defaultdict(list)
        for item in evidence:
            for sentence in _candidate_sentences(item.span_text):
                prop = _normalize_proposition(sentence)
                year = None
                ym = _YEAR.search(sentence)
                if ym:
                    year = ym.group(0)
                groups[prop].append((item, sentence, year))

        claims: list[ResearchClaim] = []
        now = utc_now()
        for prop, members in groups.items():
            if not members:
                continue
            years = {y for _, _, y in members if y}
            support_ids: list[str] = []
            contradict_ids: list[str] = []
            source_ids: set[str] = set()
            raw_examples: list[str] = []

            if len(years) > 1:
                # Split by year: earliest year as "support" set, others contradict — both preserved.
                year_to_ids: dict[str, list[str]] = defaultdict(list)
                for ev, sentence, year in members:
                    source_ids.add(ev.source_id)
                    if year:
                        year_to_ids[year].append(ev.evidence_id)
                    raw_examples.append(sentence)
                ordered_years = sorted(year_to_ids.keys())
                support_ids = list(dict.fromkeys(year_to_ids[ordered_years[0]]))
                for y in ordered_years[1:]:
                    contradict_ids.extend(year_to_ids[y])
                contradict_ids = list(dict.fromkeys(contradict_ids))
                status = ClaimStatus.DISPUTED
                proposition = re.sub(r"\byear\b", "/".join(ordered_years), prop, count=1)
                if proposition == prop:
                    proposition = f"{prop} (conflicting years: {', '.join(ordered_years)})"
            else:
                for ev, sentence, _year in members:
                    support_ids.append(ev.evidence_id)
                    source_ids.add(ev.source_id)
                    raw_examples.append(sentence)
                support_ids = list(dict.fromkeys(support_ids))
                if len(source_ids) >= 2:
                    status = ClaimStatus.SUPPORTED
                elif support_ids:
                    status = ClaimStatus.WEAKLY_SUPPORTED
                else:
                    status = ClaimStatus.UNSUPPORTED
                proposition = members[0][1][:400]

            claim = ResearchClaim(
                claim_id=str(uuid.uuid4()),
                project_id=project_id,
                proposition=proposition,
                raw_wording=raw_examples[0] if raw_examples else proposition,
                status=status,
                supporting_evidence_ids=support_ids,
                contradicting_evidence_ids=contradict_ids,
                source_diversity=len(source_ids),
                created_at=now,
                updated_at=now,
                metadata={
                    "normalized": prop,
                    "years": sorted(years),
                    "examples": raw_examples[:5],
                },
            )
            self.store.upsert_claim(claim)
            for eid in support_ids + contradict_ids:
                existing = self.store.get_evidence(eid)
                if existing is None:
                    continue
                associated = list(existing.associated_claim_ids)
                if claim.claim_id not in associated:
                    associated.append(claim.claim_id)
                    self.store.update_evidence_claims(eid, associated)
            claims.append(claim)
        return claims
