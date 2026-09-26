"""Active learning — mine verified failures into governed training candidates (U314 / W11)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TrainingCandidateLifecycle(str, Enum):
    """Experience/AL training-candidate lifecycle (distinct from ChallengerStatus)."""

    CANDIDATE = "CANDIDATE"
    EVALUATED = "EVALUATED"
    ELIGIBLE = "ELIGIBLE"
    PROMOTED = "PROMOTED"


# Kinds that may be mined into AL candidates (W11 required inputs).
AL_KINDS = frozenset(
    {
        "failure",
        "retry",
        "correction",
        "tool_error",
        "verification_failure",
        "low_candidate_agreement",
        "user_correction",
        "critic_high_severity",
        "tool_failure_pattern",
        "retrieval_miss",
        "uncertainty",
    }
)


@dataclass
class MinedCandidate:
    candidate_id: str
    kind: str
    source_ref: str
    prompt: str
    content: str
    governed: bool = False
    lifecycle: str = TrainingCandidateLifecycle.CANDIDATE.value
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "source_ref": self.source_ref,
            "prompt": self.prompt,
            "content": self.content,
            "governed": self.governed,
            "lifecycle": self.lifecycle,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "truth": {
                "mining_requires_explicit_governed_ingestion": True,
                "not_auto_added_to_training_mixture": True,
                "auto_promote_forbidden": True,
            },
        }


class ActiveLearningMiner:
    """Extract candidate examples; ingestion into datasets is an explicit second step."""

    def __init__(self) -> None:
        self._pending: dict[str, MinedCandidate] = {}

    def mine_from_events(
        self,
        events: list[dict[str, Any]],
    ) -> list[MinedCandidate]:
        created: list[MinedCandidate] = []
        for event in events:
            kind = str(event.get("kind") or event.get("type") or "").lower()
            if kind not in AL_KINDS:
                continue
            cand = MinedCandidate(
                candidate_id=f"mine_{uuid.uuid4().hex[:12]}",
                kind=kind,
                source_ref=str(event.get("source_ref") or event.get("id") or ""),
                prompt=str(event.get("prompt") or event.get("input") or ""),
                content=str(event.get("content") or event.get("error") or event.get("output") or ""),
                governed=False,
                lifecycle=TrainingCandidateLifecycle.CANDIDATE.value,
                metadata={
                    "raw_keys": sorted(event.keys()),
                    "auto_promote_forbidden": True,
                },
            )
            self._pending[cand.candidate_id] = cand
            created.append(cand)
        return created

    def govern(self, candidate_id: str, *, operator: str, note: str = "") -> MinedCandidate:
        cand = self._pending.get(candidate_id)
        if cand is None:
            raise KeyError(f"Unknown mined candidate: {candidate_id}")
        cand.governed = True
        cand.lifecycle = TrainingCandidateLifecycle.ELIGIBLE.value
        cand.metadata["governed_by"] = operator
        cand.metadata["govern_note"] = note
        cand.metadata["governed_at"] = _utc_now()
        return cand

    def mark_evaluated(
        self,
        candidate_id: str,
        *,
        score: float | None = None,
        note: str = "",
    ) -> MinedCandidate:
        cand = self._pending.get(candidate_id)
        if cand is None:
            raise KeyError(f"Unknown mined candidate: {candidate_id}")
        cand.lifecycle = TrainingCandidateLifecycle.EVALUATED.value
        if score is not None:
            cand.metadata["eval_score"] = score
        if note:
            cand.metadata["eval_note"] = note
        cand.metadata["evaluated_at"] = _utc_now()
        return cand

    def to_dataset_records(self, *, governed_only: bool = True) -> list[dict[str, Any]]:
        """Explicit second-step materialization — never auto-called by mine()."""
        items = self.list_pending(governed_only=governed_only)
        rows: list[dict[str, Any]] = []
        for cand in items:
            if governed_only and not cand.governed:
                continue
            if cand.lifecycle not in {
                TrainingCandidateLifecycle.ELIGIBLE.value,
                TrainingCandidateLifecycle.EVALUATED.value,
                TrainingCandidateLifecycle.PROMOTED.value,
            } and governed_only:
                continue
            rows.append(
                {
                    "prompt": cand.prompt,
                    "completion": cand.content,
                    "candidate_id": cand.candidate_id,
                    "kind": cand.kind,
                    "lifecycle": cand.lifecycle,
                    "source_ref": cand.source_ref,
                    "metadata": {
                        **dict(cand.metadata),
                        "auto_promote_forbidden": True,
                        "requires_operator_promotion": True,
                    },
                }
            )
        return rows

    def list_pending(self, *, governed_only: bool = False, limit: int = 100) -> list[MinedCandidate]:
        items = list(self._pending.values())
        if governed_only:
            items = [c for c in items if c.governed]
        items.sort(key=lambda c: c.created_at, reverse=True)
        return items[:limit]
