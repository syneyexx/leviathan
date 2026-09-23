"""Generic preference-record schema for DPO/IPO-style optimization (U301)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PreferenceRanking(str, Enum):
    PREFERRED = "preferred"
    TIE = "tie"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PreferenceCandidate:
    candidate_id: str
    text: str
    rank: int | None = None
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "text": self.text,
            "rank": self.rank,
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass
class PreferenceRecord:
    """Prompt/context + candidates + ranking/tie + rubric + annotator provenance."""

    preference_id: str
    prompt: str
    candidates: list[PreferenceCandidate]
    preferred_id: str | None
    rejected_id: str | None
    ranking: PreferenceRanking
    rubric: str | None = None
    profile: str | None = None
    annotator: str | None = None
    source: str = "human"  # human | verification | synthetic | mined
    context: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "preference_id": self.preference_id,
            "prompt": self.prompt,
            "candidates": [c.public_dict() for c in self.candidates],
            "preferred_id": self.preferred_id,
            "rejected_id": self.rejected_id,
            "ranking": self.ranking.value,
            "rubric": self.rubric,
            "profile": self.profile,
            "annotator": self.annotator,
            "source": self.source,
            "context": dict(self.context),
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "preference_labels_not_fabricated": True,
                "registered_is_not_trained": True,
            },
        }


def _hash_record(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_preference_record(
    *,
    prompt: str,
    preferred_text: str,
    rejected_text: str,
    rubric: str | None = None,
    profile: str | None = None,
    annotator: str | None = None,
    source: str = "human",
    context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    preference_id: str | None = None,
    tie: bool = False,
) -> PreferenceRecord:
    preferred_text = (preferred_text or "").strip()
    rejected_text = (rejected_text or "").strip()
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    if not preferred_text or not rejected_text:
        raise ValueError("preferred_text and rejected_text are required")
    if preferred_text == rejected_text and not tie:
        raise ValueError("preferred and rejected texts must differ unless tie=True")
    pref_id = f"cand_{uuid.uuid4().hex[:8]}"
    rej_id = f"cand_{uuid.uuid4().hex[:8]}"
    candidates = [
        PreferenceCandidate(candidate_id=pref_id, text=preferred_text, rank=1),
        PreferenceCandidate(candidate_id=rej_id, text=rejected_text, rank=2 if not tie else 1),
    ]
    ranking = PreferenceRanking.TIE if tie else PreferenceRanking.PREFERRED
    body = {
        "prompt": prompt,
        "preferred": preferred_text,
        "rejected": rejected_text,
        "ranking": ranking.value,
        "rubric": rubric,
        "profile": profile,
        "source": source,
        "context": dict(context or {}),
    }
    return PreferenceRecord(
        preference_id=preference_id or f"pref_{uuid.uuid4().hex[:12]}",
        prompt=prompt,
        candidates=candidates,
        preferred_id=pref_id,
        rejected_id=rej_id,
        ranking=ranking,
        rubric=rubric,
        profile=profile,
        annotator=annotator,
        source=source,
        context=dict(context or {}),
        content_hash=_hash_record(body),
        metadata=dict(metadata or {}),
    )
