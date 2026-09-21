from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from Data.modules.knowledge.retrieval import HybridRetriever, RetrievalQuery
from Data.modules.knowledge.store import KnowledgeStore
from Data.modules.memory.store import MemoryStore
from Data.modules.memory.types import MemoryKind, MemoryRecord

from .residual import ResidualHookPoint, ResidualInjectRequest


@dataclass(frozen=True)
class WorkingSlot:
    slot_id: str
    content: str
    created_at_ms: float
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "content": self.content,
            "created_at_ms": self.created_at_ms,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "tier": 0,
        }


@dataclass(frozen=True)
class NeuroMemoryHit:
    tier: int
    ref_id: str
    content: str
    score: float
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "ref_id": self.ref_id,
            "content": self.content,
            "score": self.score,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class NeuroMemoryBundle:
    query: str
    hits: tuple[NeuroMemoryHit, ...]
    tiers_queried: tuple[int, ...]
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [item.public_dict() for item in self.hits],
            "tiers_queried": list(self.tiers_queried),
            "notes": list(self.notes),
            "truth": {
                "memory_facade_does_not_fork_stores": True,
                "model_output_is_not_automatic_memory": True,
            },
        }


class WorkingMemoryBuffer:
    """Tier 0 — process-local hot memory. Not durable across restart."""

    def __init__(self, *, capacity: int = 64) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._slots: dict[str, WorkingSlot] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def write(self, content: str, *, tags: Sequence[str] | None = None, metadata: dict[str, Any] | None = None) -> WorkingSlot:
        text = content.strip()
        if not text:
            raise ValueError("Working memory content cannot be empty")
        slot = WorkingSlot(
            slot_id=str(uuid.uuid4()),
            content=text,
            created_at_ms=time.time() * 1000,
            tags=tuple(tags or ()),
            metadata=metadata or {},
        )
        with self._lock:
            self._slots[slot.slot_id] = slot
            self._order.append(slot.slot_id)
            while len(self._order) > self.capacity:
                old = self._order.pop(0)
                self._slots.pop(old, None)
        return slot

    def retrieve(self, query: str, *, limit: int = 5) -> list[NeuroMemoryHit]:
        q = query.lower().strip()
        with self._lock:
            items = list(self._slots.values())
        scored: list[NeuroMemoryHit] = []
        for slot in reversed(items):
            hay = slot.content.lower()
            score = 0.0
            if q and q in hay:
                score = 1.0
            elif q:
                tokens = [t for t in q.split() if len(t) > 2]
                if tokens:
                    score = sum(1 for t in tokens if t in hay) / len(tokens)
            if score <= 0:
                continue
            scored.append(
                NeuroMemoryHit(
                    tier=0,
                    ref_id=slot.slot_id,
                    content=slot.content,
                    score=round(score, 3),
                    provenance={"kind": "working"},
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, limit)]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._slots[sid].public_dict() for sid in self._order if sid in self._slots]

    def clear(self) -> None:
        with self._lock:
            self._slots.clear()
            self._order.clear()

    def load_slots(self, items: Sequence[dict[str, Any]]) -> int:
        loaded = 0
        self.clear()
        for item in items:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            self.write(
                content,
                tags=item.get("tags") or (),
                metadata=item.get("metadata") or {},
            )
            loaded += 1
        return loaded


class NeuroMemoryFacade:
    """Orchestrates Tier 0–2 without forking MemoryStore or KnowledgeStore."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        memory_store: MemoryStore | None = None,
        knowledge_store: KnowledgeStore | None = None,
        knowledge_retriever: HybridRetriever | None = None,
        snapshot_store: Any | None = None,
        working_capacity: int = 64,
    ) -> None:
        self.enabled = enabled
        self.memory_store = memory_store
        self.knowledge_store = knowledge_store
        self.knowledge_retriever = knowledge_retriever
        self.snapshot_store = snapshot_store
        self.working = WorkingMemoryBuffer(capacity=working_capacity)

    def write_working(self, content: str, **kwargs: Any) -> WorkingSlot:
        if not self.enabled:
            raise RuntimeError("Neuro memory tiers feature flag OFF")
        return self.working.write(content, **kwargs)

    def write_episodic(
        self,
        content: str,
        *,
        kind: MemoryKind = MemoryKind.EPISODIC,
        trust: str = "explicit",
        source: str = "neuro.tier1",
        run_id: str | None = None,
        conversation_id: str | None = None,
        tags: Sequence[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        if not self.enabled:
            raise RuntimeError("Neuro memory tiers feature flag OFF")
        if self.memory_store is None:
            raise RuntimeError("MemoryStore not configured for Tier 1")
        if kind not in {MemoryKind.EPISODIC, MemoryKind.DECISION, MemoryKind.NOTE, MemoryKind.FACT, MemoryKind.PROCEDURE, MemoryKind.PREFERENCE}:
            raise ValueError(f"Unsupported memory kind: {kind}")
        return self.memory_store.create(
            content=content,
            kind=kind,
            trust=trust,
            source=source,
            run_id=run_id,
            conversation_id=conversation_id,
            tags=list(tags or ()),
            metadata=metadata,
        )

    def retrieve(
        self,
        query: str,
        *,
        tiers: Sequence[int] = (0, 1, 2),
        limit_per_tier: int = 3,
    ) -> NeuroMemoryBundle:
        if not self.enabled:
            return NeuroMemoryBundle(
                query=query,
                hits=(),
                tiers_queried=(),
                notes=("neuro memory tiers feature flag OFF",),
            )

        hits: list[NeuroMemoryHit] = []
        notes: list[str] = []
        queried: list[int] = []

        if 0 in tiers:
            queried.append(0)
            hits.extend(self.working.retrieve(query, limit=limit_per_tier))

        if 1 in tiers:
            queried.append(1)
            if self.memory_store is None:
                notes.append("Tier1 skipped — MemoryStore unavailable")
            else:
                for record in self.memory_store.search(query, limit=limit_per_tier):
                    hits.append(
                        NeuroMemoryHit(
                            tier=1,
                            ref_id=record.memory_id,
                            content=record.content,
                            score=0.7,
                            provenance={
                                "kind": record.kind.value,
                                "trust": record.trust,
                                "source": record.source,
                            },
                        )
                    )

        if 2 in tiers:
            queried.append(2)
            if self.knowledge_retriever is not None:
                for hit in self.knowledge_retriever.search(
                    RetrievalQuery(text=query, limit=limit_per_tier, use_embeddings=False)
                ):
                    hits.append(
                        NeuroMemoryHit(
                            tier=2,
                            ref_id=hit.document_id,
                            content=hit.content[:1200],
                            score=round(float(hit.score), 3),
                            provenance={
                                "store": "knowledge_v2",
                                "chunk_id": hit.chunk_id,
                                "modality": hit.modality,
                            },
                        )
                    )
            elif self.knowledge_store is not None:
                for row in self.knowledge_store.search_lexical(query, limit=limit_per_tier):
                    doc_id = str(row.get("document_id") or row.get("id") or "")
                    content = str(row.get("chunk_content") or row.get("document_content") or row.get("content") or "")
                    if not content:
                        continue
                    hits.append(
                        NeuroMemoryHit(
                            tier=2,
                            ref_id=doc_id or str(uuid.uuid4()),
                            content=content[:1200],
                            score=0.6,
                            provenance={
                                "store": "knowledge_v2",
                                "modality": "lexical",
                                "chunk_id": row.get("chunk_id"),
                            },
                        )
                    )
            else:
                notes.append("Tier2 skipped — KnowledgeStore unavailable")

        hits.sort(key=lambda item: item.score, reverse=True)
        return NeuroMemoryBundle(
            query=query,
            hits=tuple(hits),
            tiers_queried=tuple(queried),
            notes=tuple(notes),
        )

    def project_for_residual(
        self,
        bundle: NeuroMemoryBundle,
        *,
        hook: ResidualHookPoint | None = None,
        scale: float = 0.1,
    ) -> ResidualInjectRequest | None:
        if not bundle.hits:
            return None
        top = bundle.hits[0]
        point = hook or ResidualHookPoint(layer_index=-1, name="mid_block", site="block_out")
        return ResidualInjectRequest(
            hook=point,
            mode="ADDITIVE",
            scale=scale,
            source="neuro.memory_facade",
            payload_ref=top.ref_id,
        )

    def snapshot(self, tier: int, label: str) -> Any:
        if not self.enabled:
            raise RuntimeError("Neuro memory tiers feature flag OFF")
        if self.snapshot_store is None:
            raise RuntimeError("NeuroSnapshotStore not configured")
        if tier == 0:
            payload = {"working": self.working.snapshot()}
        elif tier == 1:
            if self.memory_store is None:
                raise RuntimeError("MemoryStore unavailable for Tier 1 snapshot")
            items = self.memory_store.list(limit=200)
            payload = {
                "memories": [
                    {
                        "memory_id": item.memory_id,
                        "kind": item.kind.value,
                        "content": item.content,
                        "trust": item.trust,
                        "tags": list(item.tags),
                    }
                    for item in items
                ]
            }
        else:
            raise ValueError("Only Tier 0/1 snapshots supported (Tier 2 uses Knowledge versions)")
        return self.snapshot_store.save(label=label, tier=tier, payload=payload)

    def restore(self, snapshot_id: str) -> Any:
        if not self.enabled:
            raise RuntimeError("Neuro memory tiers feature flag OFF")
        if self.snapshot_store is None:
            raise RuntimeError("NeuroSnapshotStore not configured")
        snap = self.snapshot_store.get(snapshot_id)
        if snap is None:
            raise KeyError(f"Unknown snapshot: {snapshot_id}")
        if snap.tier == 0:
            self.working.load_slots(snap.payload.get("working") or [])
        elif snap.tier == 1:
            if self.memory_store is None:
                raise RuntimeError("MemoryStore unavailable for Tier 1 restore")
            for item in snap.payload.get("memories") or []:
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                kind_raw = str(item.get("kind") or MemoryKind.EPISODIC.value)
                try:
                    kind = MemoryKind(kind_raw)
                except ValueError:
                    kind = MemoryKind.EPISODIC
                try:
                    self.memory_store.create(
                        content=content,
                        kind=kind,
                        trust=str(item.get("trust") or "imported"),
                        source="neuro.snapshot_restore",
                        tags=item.get("tags") or [],
                        metadata={"restored_from": snapshot_id},
                    )
                except ValueError:
                    continue
        else:
            raise ValueError("Tier 2 restore not supported via neuro snapshots")
        return snap
