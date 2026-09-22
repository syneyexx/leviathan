"""Perception layer — typed, provenance-aware, bounded retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import EpistemicType


class _Searchable(Protocol):
    def search(self, query: str, limit: int = 5) -> list[Any]: ...


@dataclass(frozen=True)
class PerceptionItem:
    item_id: str
    source_type: EpistemicType
    summary: str
    source_ref: str | None = None
    trust: float = 0.5
    confidence: float = 0.5
    freshness: str = "unknown"
    authority: str = "none"
    verification_status: str = "unverified"
    payload: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_type": self.source_type.value,
            "summary": self.summary,
            "source_ref": self.source_ref,
            "trust": self.trust,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "authority": self.authority,
            "verification_status": self.verification_status,
            "payload": self.payload,
            "truth": {
                "perception_is_not_instruction": True,
                "exact_memory_is_not_neural_association": True,
            },
        }


@dataclass
class PerceptionSnapshot:
    snapshot_id: str
    items: list[PerceptionItem] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    budgets: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def by_type(self, source_type: EpistemicType) -> list[PerceptionItem]:
        return [i for i in self.items if i.source_type == source_type]

    def public_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "items": [i.public_dict() for i in self.items],
            "dropped": list(self.dropped),
            "budgets": dict(self.budgets),
            "provenance": self.provenance,
            "counts_by_type": {
                t.value: len(self.by_type(t)) for t in EpistemicType if self.by_type(t)
            },
        }


def _relevance(query: str, text: str) -> float:
    q_tokens = {t for t in query.lower().split() if len(t) > 2}
    if not q_tokens:
        return 0.1
    hay = text.lower()
    hits = sum(1 for t in q_tokens if t in hay)
    return min(1.0, hits / max(1, len(q_tokens)))


class PerceptionService:
    """Collect available information without dumping everything into context."""

    def __init__(
        self,
        *,
        knowledge_store: Any | None = None,
        memory_store: Any | None = None,
        evidence_service: Any | None = None,
        capability_catalog: Any | None = None,
        neuro_advisor: Any | None = None,
        default_budget: int = 16,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.memory_store = memory_store
        self.evidence_service = evidence_service
        self.capability_catalog = capability_catalog
        self.neuro_advisor = neuro_advisor
        self.default_budget = default_budget

    def perceive(
        self,
        query: str,
        *,
        history: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
        run_id: str | None = None,
        include_neuro: bool = False,
        budgets: dict[str, int] | None = None,
        system_state: dict[str, Any] | None = None,
    ) -> PerceptionSnapshot:
        budgets = {
            "knowledge": 4,
            "memory": 4,
            "evidence": 3,
            "neuro": 2,
            "history": 6,
            "capabilities": 4,
            "system": 2,
            **(budgets or {}),
        }
        items: list[PerceptionItem] = []
        dropped: list[str] = []

        # Conversation / user statements
        for msg in (history or [])[-budgets["history"] :]:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            items.append(
                PerceptionItem(
                    item_id=str(uuid.uuid4()),
                    source_type=EpistemicType.USER_STATEMENT
                    if role == "user"
                    else EpistemicType.MODEL_INFERENCE,
                    summary=content[:500],
                    source_ref=conversation_id,
                    trust=0.9 if role == "user" else 0.4,
                    confidence=0.9 if role == "user" else 0.45,
                    freshness="session",
                    authority="user" if role == "user" else "model",
                    verification_status="n/a",
                    payload={"role": role},
                )
            )

        # Knowledge
        if self.knowledge_store is not None and budgets["knowledge"] > 0:
            try:
                matches = self._safe_search(self.knowledge_store, query, budgets["knowledge"])
                scored = sorted(
                    (( _relevance(query, self._text(m)), m) for m in matches),
                    key=lambda p: -p[0],
                )
                for score, match in scored[: budgets["knowledge"]]:
                    if score < 0.05 and len(scored) > 1:
                        dropped.append(f"knowledge_low_relevance:{self._id(match)}")
                        continue
                    items.append(
                        PerceptionItem(
                            item_id=str(uuid.uuid4()),
                            source_type=EpistemicType.KNOWLEDGE_SOURCE,
                            summary=self._text(match)[:600],
                            source_ref=self._id(match),
                            trust=0.7,
                            confidence=min(0.9, 0.4 + score),
                            freshness="indexed",
                            authority="knowledge",
                            verification_status="source",
                            payload=self._as_dict(match),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 — perception must degrade honestly
                dropped.append(f"knowledge_error:{type(exc).__name__}")

        # Exact memory
        if self.memory_store is not None and budgets["memory"] > 0:
            try:
                matches = self._safe_search(self.memory_store, query, budgets["memory"])
                for match in matches[: budgets["memory"]]:
                    items.append(
                        PerceptionItem(
                            item_id=str(uuid.uuid4()),
                            source_type=EpistemicType.EXACT_FACT,
                            summary=self._text(match)[:500],
                            source_ref=self._id(match),
                            trust=0.85,
                            confidence=0.8,
                            freshness="stored",
                            authority="memory",
                            verification_status=str(
                                getattr(match, "trust", None)
                                or (match.get("trust") if isinstance(match, dict) else "explicit")
                            ),
                            payload=self._as_dict(match),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                dropped.append(f"memory_error:{type(exc).__name__}")

        # Evidence
        if self.evidence_service is not None and budgets["evidence"] > 0:
            try:
                matches = self._safe_list_evidence(budgets["evidence"])
                for match in matches[: budgets["evidence"]]:
                    items.append(
                        PerceptionItem(
                            item_id=str(uuid.uuid4()),
                            source_type=EpistemicType.EVIDENCE,
                            summary=self._text(match)[:500],
                            source_ref=self._id(match),
                            trust=0.9,
                            confidence=0.85,
                            freshness="verified",
                            authority="evidence",
                            verification_status=str(
                                getattr(match, "status", None)
                                or (match.get("status") if isinstance(match, dict) else "unknown")
                            ),
                            payload=self._as_dict(match),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                dropped.append(f"evidence_error:{type(exc).__name__}")

        # Capability shortlist (availability ≠ authorization)
        if self.capability_catalog is not None and budgets["capabilities"] > 0:
            try:
                found = self.capability_catalog.search(query, limit=budgets["capabilities"])
                for cap in found:
                    items.append(
                        PerceptionItem(
                            item_id=str(uuid.uuid4()),
                            source_type=EpistemicType.SYSTEM_STATE,
                            summary=f"capability:{getattr(cap, 'id', '?')} available={getattr(cap, 'available', False)}",
                            source_ref=getattr(cap, "id", None),
                            trust=1.0,
                            confidence=1.0,
                            freshness="live",
                            authority="capability_catalog",
                            verification_status="catalog",
                            payload=cap.public_dict() if hasattr(cap, "public_dict") else {"id": getattr(cap, "id", None)},
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                dropped.append(f"capability_error:{type(exc).__name__}")

        # Neuro advisory associations (never exact facts)
        if include_neuro and self.neuro_advisor is not None and budgets["neuro"] > 0:
            try:
                assessment = self.neuro_advisor.assess(query)
                signals = list(getattr(assessment, "signals", ()) or ())[: budgets["neuro"]]
                for sig in signals:
                    label = getattr(sig, "label", None) or getattr(sig, "name", None) or str(sig)
                    items.append(
                        PerceptionItem(
                            item_id=str(uuid.uuid4()),
                            source_type=EpistemicType.NEURAL_ASSOCIATION,
                            summary=f"[advisory neural] {label}",
                            source_ref=getattr(sig, "signal_id", None),
                            trust=0.2,
                            confidence=float(getattr(sig, "strength", 0.3) or 0.3),
                            freshness="advisory",
                            authority="none",
                            verification_status="advisory_only",
                            payload=sig.public_dict() if hasattr(sig, "public_dict") else {"label": label},
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                dropped.append(f"neuro_error:{type(exc).__name__}")

        # System state
        if system_state and budgets["system"] > 0:
            for key, value in list(system_state.items())[: budgets["system"]]:
                items.append(
                    PerceptionItem(
                        item_id=str(uuid.uuid4()),
                        source_type=EpistemicType.SYSTEM_STATE,
                        summary=f"{key}={value}",
                        source_ref=str(key),
                        trust=1.0,
                        confidence=1.0,
                        freshness="live",
                        authority="system",
                        verification_status="runtime",
                        payload={"key": key, "value": value},
                    )
                )

        # Hard total budget
        total_budget = self.default_budget
        if len(items) > total_budget:
            ranked = sorted(items, key=lambda i: (-i.trust * i.confidence, i.source_type.value))
            kept = ranked[:total_budget]
            for item in ranked[total_budget:]:
                dropped.append(f"budget:{item.source_type.value}:{item.source_ref or item.item_id}")
            items = kept

        return PerceptionSnapshot(
            snapshot_id=str(uuid.uuid4()),
            items=items,
            dropped=dropped,
            budgets=budgets,
            provenance={
                "query": query[:200],
                "run_id": run_id,
                "conversation_id": conversation_id,
            },
        )

    def _safe_search(self, store: Any, query: str, limit: int) -> list[Any]:
        if hasattr(store, "search"):
            try:
                return list(store.search(query, limit=limit) or [])
            except TypeError:
                return list(store.search(query, limit) or [])
        if hasattr(store, "search_knowledge"):
            return list(store.search_knowledge(query, limit=limit) or [])
        return []

    def _safe_list_evidence(self, limit: int) -> list[Any]:
        svc = self.evidence_service
        if svc is None:
            return []
        if hasattr(svc, "list_recent"):
            return list(svc.list_recent(limit=limit) or [])
        if hasattr(svc, "store") and hasattr(svc.store, "list_recent"):
            return list(svc.store.list_recent(limit=limit) or [])
        if hasattr(svc, "list"):
            return list(svc.list() or [])[:limit]
        return []

    @staticmethod
    def _text(obj: Any) -> str:
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return str(obj.get("content") or obj.get("claim") or obj.get("title") or obj)
        for attr in ("content", "claim", "text", "summary"):
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                if val:
                    return str(val)
        if hasattr(obj, "public_dict"):
            d = obj.public_dict()
            return str(d.get("content") or d.get("claim") or d)
        return str(obj)

    @staticmethod
    def _id(obj: Any) -> str | None:
        if isinstance(obj, dict):
            return obj.get("id") or obj.get("evidence_id") or obj.get("memory_id") or obj.get("document_id")
        for attr in ("id", "evidence_id", "memory_id", "document_id"):
            if hasattr(obj, attr) and getattr(obj, attr):
                return str(getattr(obj, attr))
        return None

    @staticmethod
    def _as_dict(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return dict(obj)
        if hasattr(obj, "public_dict"):
            return obj.public_dict()
        if hasattr(obj, "as_context_item"):
            return obj.as_context_item()
        return {"repr": str(obj)[:200]}
