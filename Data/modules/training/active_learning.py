"""Active learning — mine verified failures into governed training candidates (U314)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class MinedCandidate:
    candidate_id: str
    kind: str  # failure | retry | correction | tool_error
    source_ref: str
    prompt: str
    content: str
    governed: bool = False
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
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "truth": {
                "mining_requires_explicit_governed_ingestion": True,
                "not_auto_added_to_training_mixture": True,
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
            if kind not in {"failure", "retry", "correction", "tool_error"}:
                continue
            cand = MinedCandidate(
                candidate_id=f"mine_{uuid.uuid4().hex[:12]}",
                kind=kind,
                source_ref=str(event.get("source_ref") or event.get("id") or ""),
                prompt=str(event.get("prompt") or event.get("input") or ""),
                content=str(event.get("content") or event.get("error") or event.get("output") or ""),
                governed=False,
                metadata={"raw_keys": sorted(event.keys())},
            )
            self._pending[cand.candidate_id] = cand
            created.append(cand)
        return created

    def govern(self, candidate_id: str, *, operator: str, note: str = "") -> MinedCandidate:
        cand = self._pending.get(candidate_id)
        if cand is None:
            raise KeyError(f"Unknown mined candidate: {candidate_id}")
        cand.governed = True
        cand.metadata["governed_by"] = operator
        cand.metadata["govern_note"] = note
        cand.metadata["governed_at"] = _utc_now()
        return cand

    def list_pending(self, *, governed_only: bool = False, limit: int = 100) -> list[MinedCandidate]:
        items = list(self._pending.values())
        if governed_only:
            items = [c for c in items if c.governed]
        items.sort(key=lambda c: c.created_at, reverse=True)
        return items[:limit]
