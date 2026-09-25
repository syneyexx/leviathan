"""Strategy Library — persist, recall, lessons, promotion, provenance (T6).

G22: hydrate/recall strategy memories with causal available_at filtering.
G31: explicit promotion state machine (no silent paper/live promotion).
G53: full provenance fingerprint over dataset/strategy/code/seed bindings.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from .epistemic import is_available
from .experiments import StrategyMemoryEntry, StrategyMemoryIndex
from .types import MarketSimError, StrategyStatus


# Extended promotion statuses (G31). Legacy ACTIVE/DRAFT/ARCHIVED remain valid.
PROMOTION_STATES: frozenset[str] = frozenset(
    {
        StrategyStatus.DRAFT.value,
        "RESEARCH",
        "CANDIDATE",
        "PAPER_READY",
        StrategyStatus.ACTIVE.value,
        "REJECTED",
        StrategyStatus.ARCHIVED.value,
    }
)

# Directed edges of the promotion state machine.
PROMOTION_TRANSITIONS: dict[str, frozenset[str]] = {
    StrategyStatus.DRAFT.value: frozenset({"RESEARCH", StrategyStatus.ARCHIVED.value}),
    "RESEARCH": frozenset(
        {"CANDIDATE", "REJECTED", StrategyStatus.ARCHIVED.value, StrategyStatus.DRAFT.value}
    ),
    "CANDIDATE": frozenset(
        {"PAPER_READY", "REJECTED", "RESEARCH", StrategyStatus.ARCHIVED.value}
    ),
    "PAPER_READY": frozenset(
        {StrategyStatus.ACTIVE.value, "REJECTED", StrategyStatus.ARCHIVED.value}
    ),
    StrategyStatus.ACTIVE.value: frozenset(
        {StrategyStatus.ARCHIVED.value, "PAPER_READY", "RESEARCH"}
    ),
    "REJECTED": frozenset({"RESEARCH", StrategyStatus.ARCHIVED.value}),
    StrategyStatus.ARCHIVED.value: frozenset(),  # terminal
}


def can_promote(from_status: str, to_status: str) -> bool:
    src = str(from_status or "").upper()
    dst = str(to_status or "").upper()
    if dst not in PROMOTION_STATES:
        return False
    allowed = PROMOTION_TRANSITIONS.get(src)
    if allowed is None:
        return False
    return dst in allowed


def assert_promotion_allowed(from_status: str, to_status: str) -> None:
    if not can_promote(from_status, to_status):
        raise MarketSimError(
            "INVALID_PROMOTION",
            f"Cannot promote {from_status} → {to_status}; "
            f"allowed={sorted(PROMOTION_TRANSITIONS.get(str(from_status or '').upper(), ()))}",
            http_status=409,
        )


def compute_provenance_fingerprint(
    *,
    market_dataset_hash: str,
    strategy_content_hash: str,
    code_version: str = "market_sim-t6",
    feature_pipeline_version: str = "market_features-2",
    execution_model_version: str = "next_bar_open-1",
    cost_model: dict[str, Any] | None = None,
    random_seed: int = 0,
    strategy_version: int | None = None,
    brain_policy_ref: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Stable SHA-256 fingerprint of everything that must match for reproducibility (G53)."""
    payload = {
        "market_dataset_hash": market_dataset_hash,
        "strategy_content_hash": strategy_content_hash,
        "strategy_version": strategy_version,
        "code_version": code_version,
        "feature_pipeline_version": feature_pipeline_version,
        "execution_model_version": execution_model_version,
        "cost_model": cost_model or {},
        "random_seed": int(random_seed),
        "brain_policy_ref": brain_policy_ref,
        "extra": extra or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def memory_entry_from_row(row: dict[str, Any]) -> StrategyMemoryEntry:
    return StrategyMemoryEntry(
        memory_id=str(row["memory_id"]),
        strategy_id=str(row["strategy_id"]),
        strategy_version=int(row.get("strategy_version") or 0),
        features=dict(row.get("features") or {}),
        applicability=dict(row.get("applicability") or {}),
        outcome_summary=str(row.get("outcome_summary") or ""),
        trial_id=row.get("trial_id"),
        created_at=str(row.get("created_at") or ""),
        available_at=str(row.get("available_at") or ""),
        rejected=bool(row.get("rejected")),
    )


def hydrate_memory_index(
    rows: Sequence[dict[str, Any]],
    *,
    as_of_ts: str | None = None,
) -> StrategyMemoryIndex:
    """Build an in-memory index from persisted rows; optional as_of pre-filter."""
    index = StrategyMemoryIndex()
    for row in rows:
        available = str(row.get("available_at") or "")
        if as_of_ts and available and not is_available(available_at=available, as_of=as_of_ts):
            continue
        index.add(memory_entry_from_row(row))
    return index


@dataclass
class StrategyLesson:
    """Distilled lesson from a trial/memory — never a live trade signal."""

    lesson_id: str
    strategy_id: str
    strategy_version: int
    claim: str
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    applies_to: list[str] = field(default_factory=list)
    confidence: float = 0.0
    rejected: bool = False
    trial_id: str | None = None
    available_at: str = ""
    created_at: str = ""
    trust: str = "agent_proposed"

    def public_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "claim": self.claim,
            "evidence_refs": self.evidence_refs,
            "applies_to": self.applies_to,
            "confidence": self.confidence,
            "rejected": self.rejected,
            "trial_id": self.trial_id,
            "available_at": self.available_at,
            "created_at": self.created_at,
            "trust": self.trust,
            "truth": {
                "lesson_is_not_a_trade_signal": True,
                "requires_as_of_for_recall": True,
            },
        }


def lesson_from_memory(entry: StrategyMemoryEntry | dict[str, Any]) -> StrategyLesson:
    if isinstance(entry, StrategyMemoryEntry):
        data = entry.public_dict()
    else:
        data = dict(entry)
    claim = str(data.get("outcome_summary") or "").strip() or "unnamed outcome"
    return StrategyLesson(
        lesson_id=str(uuid.uuid4()),
        strategy_id=str(data["strategy_id"]),
        strategy_version=int(data.get("strategy_version") or 0),
        claim=claim,
        evidence_refs=[{"trial_id": data.get("trial_id"), "memory_id": data.get("memory_id")}],
        applies_to=list((data.get("applicability") or {}).keys()),
        confidence=0.4 if data.get("rejected") else 0.6,
        rejected=bool(data.get("rejected")),
        trial_id=data.get("trial_id"),
        available_at=str(data.get("available_at") or ""),
        created_at=str(data.get("created_at") or ""),
        trust="agent_proposed",
    )


class StrategyLibrary:
    """Persist / recall / lessons façade over Store strategy memories (G22)."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def persist_memory(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not entry.get("memory_id"):
            entry = {**entry, "memory_id": str(uuid.uuid4())}
        if not entry.get("available_at"):
            raise MarketSimError(
                "MEMORY_REQUIRES_AVAILABLE_AT",
                "strategy memory must set available_at for causal recall",
                http_status=400,
            )
        return self.store.save_strategy_memory(entry)

    def recall(
        self,
        *,
        strategy_id: str | None = None,
        as_of_ts: str,
        features: dict[str, Any] | None = None,
        limit: int = 10,
        include_rejected: bool = True,
    ) -> list[dict[str, Any]]:
        """Causal recall — only memories with available_at <= as_of_ts."""
        if not as_of_ts:
            raise MarketSimError(
                "RECALL_REQUIRES_AS_OF",
                "strategy memory recall requires as_of_ts",
                http_status=400,
            )
        rows = self.store.list_strategy_memories(
            strategy_id=strategy_id, as_of_ts=as_of_ts, limit=max(limit * 4, 50)
        )
        index = hydrate_memory_index(rows, as_of_ts=as_of_ts)
        hits = index.search(as_of_ts=as_of_ts, features=features, limit=limit * 2)
        out = []
        for h in hits:
            if not include_rejected and h.rejected:
                continue
            out.append(h.public_dict())
            if len(out) >= limit:
                break
        return out

    def lessons(
        self,
        *,
        strategy_id: str | None = None,
        as_of_ts: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        memories = self.recall(
            strategy_id=strategy_id, as_of_ts=as_of_ts, limit=limit, include_rejected=True
        )
        return [lesson_from_memory(m).public_dict() for m in memories]

    def hydrate_for_run(
        self,
        *,
        strategy_id: str | None,
        as_of_ts: str | None = None,
        limit: int = 200,
    ) -> StrategyMemoryIndex:
        rows = self.store.list_strategy_memories(
            strategy_id=strategy_id, as_of_ts=as_of_ts, limit=limit
        )
        # Also load global lessons if strategy-scoped empty (still causal via as_of).
        if strategy_id and not rows:
            rows = self.store.list_strategy_memories(as_of_ts=as_of_ts, limit=limit)
        return hydrate_memory_index(rows, as_of_ts=as_of_ts)
