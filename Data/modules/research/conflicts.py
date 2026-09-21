"""Contradiction handling — never silently resolve conflicting evidence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .store import ResearchStore
from .types import ClaimStatus, ResearchClaim, ResearchConflict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConflictDetector:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

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
            summary = (
                f"Conflicting evidence for claim: {claim.proposition}"
                if not years
                else f"Sources disagree on timing ({', '.join(str(y) for y in years)}): {claim.proposition}"
            )
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
                    "years": years or [],
                    "note": (
                        "Both supporting and contradicting evidence are retained. "
                        "Report must express uncertainty rather than picking a side."
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
