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
    kind: str  # goal | subgoal | fact | hypothesis | observation | blocker | question | capability | plan | constraint | evidence
    content: str
    priority: float
    source_type: EpistemicType = EpistemicType.SYSTEM_STATE
    provenance: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    relevance: float = 0.5
    recency: float = 1.0
    novelty: float = 0.5
    authority: float = 0.5
    task_linkage: float = 0.5
    token_cost: int = 0
    belief_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "content": self.content,
            "priority": self.priority,
            "source_type": self.source_type.value,
            "provenance": self.provenance,
            "verified": self.verified,
            "relevance": self.relevance,
            "recency": self.recency,
            "novelty": self.novelty,
            "authority": self.authority,
            "task_linkage": self.task_linkage,
            "token_cost": self.token_cost,
            "belief_id": self.belief_id,
        }

    def selection_score(self) -> float:
        """Composite score for context selection — not a truth probability."""
        return round(
            0.30 * self.priority
            + 0.25 * self.relevance
            + 0.15 * self.recency
            + 0.10 * self.novelty
            + 0.10 * self.authority
            + 0.10 * self.task_linkage
            + (0.05 if self.verified else 0.0),
            4,
        )


# Kind priority boosts used during eviction ranking.
_KIND_BOOST: dict[str, float] = {
    "goal": 1.0,
    "blocker": 0.95,
    "criteria": 0.9,
    "constraint": 0.98,
    "observation": 0.8,
    "evidence": 0.82,
    "fact": 0.75,
    "hypothesis": 0.55,
    "question": 0.5,
    "capability": 0.45,
    "plan": 0.7,
    "subgoal": 0.85,
    "tool_result": 0.78,
    "agent_result": 0.78,
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
        relevance: float = 0.5,
        recency: float = 1.0,
        novelty: float = 0.5,
        authority: float = 0.5,
        task_linkage: float = 0.5,
        token_cost: int = 0,
        belief_id: str | None = None,
    ) -> WorkingMemoryItem:
        boost = _KIND_BOOST.get(kind, 0.4)
        pri = float(priority) if priority is not None else boost
        if verified:
            pri = min(1.0, pri + 0.1)
        if source_type == EpistemicType.NEURAL_ASSOCIATION:
            kind = "neuro" if kind not in _KIND_BOOST else kind
            pri = min(pri, 0.35)
            verified = False
        if kind == "constraint":
            pri = max(pri, 0.98)
            verified = True
        wid = item_id or self._next_id(kind)
        item = WorkingMemoryItem(
            item_id=wid,
            kind=kind,
            content=content.strip(),
            priority=max(0.0, min(1.0, pri)),
            source_type=source_type,
            provenance=dict(provenance or {}),
            verified=verified and source_type != EpistemicType.NEURAL_ASSOCIATION,
            relevance=max(0.0, min(1.0, float(relevance))),
            recency=max(0.0, min(1.0, float(recency))),
            novelty=max(0.0, min(1.0, float(novelty))),
            authority=max(0.0, min(1.0, float(authority))),
            task_linkage=max(0.0, min(1.0, float(task_linkage))),
            token_cost=max(0, int(token_cost)),
            belief_id=belief_id,
        )
        self.items[wid] = item
        self._evict_if_needed()
        return item

    def get(self, item_id: str) -> WorkingMemoryItem | None:
        return self.items.get(item_id)

    def remove(self, item_id: str) -> None:
        self.items.pop(item_id, None)

    def pin_constraints(self, constraints: list[str]) -> list[WorkingMemoryItem]:
        """Pin hard constraints so compaction cannot silently drop them."""
        pinned: list[WorkingMemoryItem] = []
        for c in constraints:
            pinned.append(
                self.upsert(
                    "constraint",
                    c,
                    priority=1.0,
                    verified=True,
                    relevance=1.0,
                    authority=1.0,
                    task_linkage=1.0,
                    item_id=f"wm-constraint-{abs(hash(c)) % 10_000_000}",
                )
            )
        return pinned

    def select_for_context(self, *, token_budget: int = 2000, limit: int = 16) -> list[WorkingMemoryItem]:
        ranked = sorted(self.items.values(), key=lambda i: (-i.selection_score(), i.item_id))
        must = [i for i in ranked if i.kind in {"goal", "constraint", "criteria", "blocker"}]
        rest = [i for i in ranked if i not in must]
        selected: list[WorkingMemoryItem] = []
        used = 0
        for item in must + rest:
            cost = item.token_cost or max(8, len(item.content) // 4)
            if selected and used + cost > token_budget and item.kind not in {"goal", "constraint"}:
                continue
            selected.append(item)
            used += cost
            if len(selected) >= limit:
                break
        return selected

    def _rank_key(self, item: WorkingMemoryItem) -> tuple:
        return (
            item.selection_score(),
            item.priority,
            1 if item.verified else 0,
            _KIND_BOOST.get(item.kind, 0.4),
        )

    def _evict_if_needed(self) -> list[str]:
        evicted: list[str] = []
        while len(self.items) > self.capacity:
            victim = min(self.items.values(), key=self._rank_key)
            protected = [i for i in self.items.values() if i.kind in {"goal", "constraint"}]
            if victim.kind in {"goal", "constraint"} and len(protected) <= 1:
                candidates = [i for i in self.items.values() if i.item_id != victim.item_id]
                if not candidates:
                    break
                victim = min(candidates, key=self._rank_key)
            if victim.kind == "constraint":
                non_c = [i for i in self.items.values() if i.kind != "constraint"]
                if non_c:
                    victim = min(non_c, key=self._rank_key)
                else:
                    break
            del self.items[victim.item_id]
            evicted.append(victim.item_id)
        return evicted

    def set_goal(self, goal: str) -> WorkingMemoryItem:
        existing = [i for i in self.items.values() if i.kind == "goal"]
        for item in existing:
            self.remove(item.item_id)
        return self.upsert("goal", goal, priority=1.0, verified=True, relevance=1.0, task_linkage=1.0)

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
            novelty=0.7,
        )

    def list_by_kind(self, kind: str) -> list[WorkingMemoryItem]:
        return [i for i in self.items.values() if i.kind == kind]

    def ranked(self, *, limit: int | None = None) -> list[WorkingMemoryItem]:
        items = sorted(self.items.values(), key=lambda i: (-i.selection_score(), -i.priority, i.item_id))
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
                "hard_constraints_are_pinned": True,
            },
        }

    def saturation(self) -> float:
        return round(len(self.items) / float(self.capacity), 3)
