"""Run-scoped shared blackboard for multi-agent findings (U146)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class BlackboardEntry:
    entry_id: str
    kind: str  # finding | hypothesis | artifact | open_question | decision
    content: str
    author: str
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)
    supersedes: str | None = None
    created_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "kind": self.kind,
            "content": self.content,
            "author": self.author,
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
            "supersedes": self.supersedes,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class AgentBlackboard:
    """Shared findings board — not a private agent database."""

    def __init__(self, *, run_id: str | None = None) -> None:
        self.run_id = run_id
        self._entries: dict[str, BlackboardEntry] = {}
        self._superseded: set[str] = set()

    def post(
        self,
        *,
        kind: str,
        content: str,
        author: str,
        confidence: float = 0.5,
        provenance: dict[str, Any] | None = None,
        supersedes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BlackboardEntry:
        entry = BlackboardEntry(
            entry_id=str(uuid.uuid4()),
            kind=kind,
            content=content.strip(),
            author=author,
            confidence=max(0.0, min(1.0, float(confidence))),
            provenance=dict(provenance or {}),
            supersedes=supersedes,
            metadata=dict(metadata or {}),
        )
        if supersedes and supersedes in self._entries:
            self._superseded.add(supersedes)
        self._entries[entry.entry_id] = entry
        return entry

    def get(self, entry_id: str) -> BlackboardEntry | None:
        return self._entries.get(entry_id)

    def list(
        self,
        *,
        kind: str | None = None,
        include_superseded: bool = False,
        limit: int = 100,
    ) -> list[BlackboardEntry]:
        items = list(self._entries.values())
        if not include_superseded:
            items = [e for e in items if e.entry_id not in self._superseded]
        if kind:
            items = [e for e in items if e.kind == kind]
        items.sort(key=lambda e: e.created_at)
        return items[: max(1, min(limit, 500))]

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "entries": [e.public_dict() for e in self.list(include_superseded=False)],
            "superseded_ids": sorted(self._superseded),
            "truth": {
                "blackboard_is_not_canonical_memory": True,
                "provenance_required": True,
            },
        }
