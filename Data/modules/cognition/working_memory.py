"""Bounded WorkingMemory for active cognitive runs.

Distinct from Neuro ``WorkingMemoryBuffer`` (advisory tier-0).
This is the Cognitive Runtime workspace — not durable exact Memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import EpistemicType


@dataclass
class WorkingMemoryItem:
    item_id: str
    kind: str  # goal | subgoal | fact | hypothesis | observation | blocker | question | capability | plan
    content: str
    priority: float
    source_type: EpistemicType = EpistemicType.SYSTEM_STATE
    provenance: dict[str, Any] = field(default_factory=dict)
    verified: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "content": self.content,
            "priority": self.priority,
            "source_type": self.source_type.value,
            "provenance": self.provenance,
            "verified": self.verified,
        }


# Kind priority boosts used during eviction ranking.
_KIND_BOOST: dict[str, float] = {
    "goal": 1.0,
    "blocker": 0.95,
    "criteria": 0.9,
    "observation": 0.8,
    "fact": 0.75,
    "hypothesis": 0.55,
    "question": 0.5,
    "capability": 0.45,
    "plan": 0.7,
    "subgoal": 0.85,
    "neuro": 0.25,
}


@dataclass
class WorkingMemory:
    """Bounded cognitive workspace with explicit eviction."""

    capacity: int = 32
    items: dict[str, WorkingMemoryItem] = field(default_factory=dict)
    _seq: int = 0

    def __post_init__(self) -> None:
        if self.capacity < 4:
            raise ValueError("WorkingMemory capacity must be >= 4")

    def _next_id(self, kind: str) -> str:
        self._seq += 1
        return f"wm-{kind}-{self._seq}"

    def upsert(
        self,
        kind: str,
        content: str,
        *,
        priority: float | None = None,
        source_type: EpistemicType = EpistemicType.SYSTEM_STATE,
        provenance: dict[str, Any] | None = None,
        verified: bool = False,
        item_id: str | None = None,
    ) -> WorkingMemoryItem:
        boost = _KIND_BOOST.get(kind, 0.4)
        pri = float(priority) if priority is not None else boost
        if verified:
            pri = min(1.0, pri + 0.1)
        # Neuro associations stay advisory and lower priority by default.
        if source_type == EpistemicType.NEURAL_ASSOCIATION:
            kind = "neuro" if kind not in _KIND_BOOST else kind
            pri = min(pri, 0.35)
            verified = False
        wid = item_id or self._next_id(kind)
        item = WorkingMemoryItem(
            item_id=wid,
            kind=kind,
            content=content.strip(),
            priority=max(0.0, min(1.0, pri)),
            source_type=source_type,
            provenance=dict(provenance or {}),
            verified=verified and source_type != EpistemicType.NEURAL_ASSOCIATION,
        )
        self.items[wid] = item
        self._evict_if_needed()
        return item

    def get(self, item_id: str) -> WorkingMemoryItem | None:
        return self.items.get(item_id)

    def remove(self, item_id: str) -> None:
        self.items.pop(item_id, None)

    def _rank_key(self, item: WorkingMemoryItem) -> tuple:
        # Lower tuple = evict first.
        return (
            item.priority,
            1 if item.verified else 0,
            _KIND_BOOST.get(item.kind, 0.4),
        )

    def _evict_if_needed(self) -> list[str]:
        evicted: list[str] = []
        while len(self.items) > self.capacity:
            victim = min(self.items.values(), key=self._rank_key)
            # Never evict the primary goal if it is the only goal.
            goals = [i for i in self.items.values() if i.kind == "goal"]
            if victim.kind == "goal" and len(goals) <= 1:
                candidates = [i for i in self.items.values() if i.item_id != victim.item_id]
                if not candidates:
                    break
                victim = min(candidates, key=self._rank_key)
            del self.items[victim.item_id]
            evicted.append(victim.item_id)
        return evicted

    def set_goal(self, goal: str) -> WorkingMemoryItem:
        existing = [i for i in self.items.values() if i.kind == "goal"]
        for item in existing:
            self.remove(item.item_id)
        return self.upsert("goal", goal, priority=1.0, verified=True)

    def add_blocker(self, content: str, *, provenance: dict[str, Any] | None = None) -> WorkingMemoryItem:
        return self.upsert("blocker", content, priority=0.95, provenance=provenance)

    def add_observation(
        self,
        content: str,
        *,
        source_type: EpistemicType = EpistemicType.TOOL_OBSERVATION,
        provenance: dict[str, Any] | None = None,
    ) -> WorkingMemoryItem:
        return self.upsert(
            "observation",
            content,
            priority=0.8,
            source_type=source_type,
            provenance=provenance,
        )

    def list_by_kind(self, kind: str) -> list[WorkingMemoryItem]:
        return [i for i in self.items.values() if i.kind == kind]

    def ranked(self, *, limit: int | None = None) -> list[WorkingMemoryItem]:
        items = sorted(self.items.values(), key=lambda i: (-i.priority, i.item_id))
        if limit is not None:
            return items[:limit]
        return items

    def public_dict(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity,
            "count": len(self.items),
            "items": [i.public_dict() for i in self.ranked()],
            "truth": {
                "working_memory_is_not_durable_exact_memory": True,
                "neuro_items_are_advisory": True,
            },
        }

    def saturation(self) -> float:
        return round(len(self.items) / float(self.capacity), 3)
