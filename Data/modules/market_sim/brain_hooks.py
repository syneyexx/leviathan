"""Brain retrieval hooks — Neuro / Knowledge / Memory / Evidence (advisory only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .epistemic import EpistemicFirewall, is_available, resolve_available_at


class BrainMiss:
    pass


@dataclass
class BrainRetrieval:
    hits: list[dict[str, Any]] = field(default_factory=list)
    miss: bool = True
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "miss": self.miss,
            "notes": self.notes,
            "truth": {
                "brain_is_advisory": True,
                "model_output_is_not_evidence": True,
                "neural_signal_is_not_authority": True,
                "time_sensitive_filtered_by_available_at": True,
            },
        }


class KnowledgeSearcher(Protocol):
    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]: ...


class MemorySearcher(Protocol):
    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]: ...


class EvidenceSearcher(Protocol):
    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]: ...


class NeuroAssessor(Protocol):
    def assess(self, text: str) -> Any: ...


class BrainFacade:
    """Optional facades — missing brain components produce honest misses."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeSearcher | None = None,
        memory: MemorySearcher | None = None,
        evidence: EvidenceSearcher | None = None,
        neuro: NeuroAssessor | None = None,
        enabled_deps: list[str] | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.memory = memory
        self.evidence = evidence
        self.neuro = neuro
        self.enabled_deps = list(enabled_deps or ["knowledge", "memory", "neuro", "evidence"])

    def retrieve(
        self,
        query: str,
        *,
        dependencies: list[str] | None = None,
        limit: int = 3,
        as_of: str | None = None,
        firewall: EpistemicFirewall | None = None,
        time_sensitive: bool = True,
    ) -> BrainRetrieval:
        """Retrieve brain hits.

        With ``as_of`` / ``firewall``, time-sensitive hits whose ``available_at``
        (or conservative fallback stamp) is after the decision time are dropped.
        Untimestamped hits are dropped when ``time_sensitive`` is True (historical
        default). Neuro assessments are generated at decision time and kept.
        """
        retrieval = self._retrieve(query, dependencies=dependencies, limit=limit)
        boundary = as_of
        fw = firewall
        if fw is not None:
            boundary = fw.as_of
        if not boundary:
            return retrieval
        kept: list[dict[str, Any]] = []
        dropped = 0
        for hit in retrieval.hits:
            # Neuro assessments are advisory hypotheses generated at decision time.
            if hit.get("source") == "neuro":
                kept.append(hit)
                continue
            stamp = resolve_available_at(hit)
            if stamp is None:
                # Untimestamped material is treated as general / timeless knowledge.
                kept.append(hit)
                continue
            if not is_available(available_at=stamp, as_of=boundary):
                dropped += 1
                if fw is not None:
                    fw.violations += 1
                continue
            kept.append(hit)
        notes = list(retrieval.notes)
        if dropped:
            notes.append(f"as_of filter dropped {dropped} hit(s) newer than {boundary}")
        return BrainRetrieval(hits=kept, miss=len(kept) == 0, notes=notes)

    def _retrieve(
        self,
        query: str,
        *,
        dependencies: list[str] | None = None,
        limit: int = 3,
    ) -> BrainRetrieval:
        deps = dependencies or self.enabled_deps
        hits: list[dict[str, Any]] = []
        notes: list[str] = []

        if "knowledge" in deps:
            if self.knowledge is None:
                notes.append("knowledge facade unavailable")
            else:
                try:
                    for item in self.knowledge.search(query, limit=limit):
                        hits.append({"source": "knowledge", "provenance": "knowledge_v2", **item})
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"knowledge error: {exc}")

        if "memory" in deps:
            if self.memory is None:
                notes.append("memory facade unavailable")
            else:
                try:
                    for item in self.memory.search(query, limit=limit):
                        hits.append({"source": "memory", "provenance": "memory_store", **item})
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"memory error: {exc}")

        if "evidence" in deps:
            if self.evidence is None:
                notes.append("evidence facade unavailable")
            else:
                try:
                    for item in self.evidence.search(query, limit=limit):
                        hits.append({"source": "evidence", "provenance": "evidence_store", **item})
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"evidence error: {exc}")

        if "neuro" in deps:
            if self.neuro is None:
                notes.append("neuro facade unavailable")
            else:
                try:
                    assessment = self.neuro.assess(query)
                    payload = (
                        assessment.public_dict()
                        if hasattr(assessment, "public_dict")
                        else {"raw": str(assessment)}
                    )
                    hits.append(
                        {
                            "source": "neuro",
                            "provenance": "neuro_advisor_advisory_only",
                            "assessment": payload,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"neuro error: {exc}")

        return BrainRetrieval(hits=hits, miss=len(hits) == 0, notes=notes)

    def retrieve_trading(self, request: Any, *, firewall: EpistemicFirewall | None = None) -> Any:
        """Typed trading retrieval via canonical adapter when knowledge supports it."""
        knowledge = self.knowledge
        if knowledge is not None and hasattr(knowledge, "retrieve_trading"):
            return knowledge.retrieve_trading(request, firewall=firewall)
        # Fallback: plain query through existing retrieve path.
        from .trading_brain import TradingRetrievalRequest, TradingRetrievalResult, TradingRetrievalHit

        if not isinstance(request, TradingRetrievalRequest):
            request = TradingRetrievalRequest(query=str(getattr(request, "query", request)))
        raw = self.retrieve(
            request.expanded_query(),
            limit=request.max_hits,
            as_of=request.decision_as_of,
            firewall=firewall,
        )
        hits = [
            TradingRetrievalHit(
                source_kind=str(h.get("source") or "knowledge"),
                document_id=h.get("document_id") or h.get("documentId"),
                title=str(h.get("title") or ""),
                content_excerpt=str(h.get("content") or h.get("contentExcerpt") or "")[:800],
                score=h.get("score"),
                published_at=h.get("published_at") or h.get("publishedAt"),
                available_at=h.get("available_at") or h.get("availableAt"),
                retrieval_mode=str(h.get("retrievalMode") or "lexical"),
                embeddings_semantic=h.get("embeddingsSemantic"),
            )
            for h in raw.hits
            if isinstance(h, dict)
        ]
        return TradingRetrievalResult(
            hits=hits,
            retrieval_mode="lexical",
            embeddings_semantic=False,
            notes=list(raw.notes) + ["retrieve_trading_fallback_plain"],
            miss=len(hits) == 0,
            request=request.public_dict(),
        )


class NullKnowledge:
    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        return []


class NullMemory:
    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        return []


class NullEvidence:
    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        return []


def adapt_knowledge_store(
    store: Any,
    *,
    hybrid_retriever: Any | None = None,
    staged_retriever: Any | None = None,
    brain_access: Any | None = None,
) -> KnowledgeSearcher:
    """Adapt KnowledgeStore (and optional canonical retrievers) for BrainFacade.

    Prefer Hybrid/Staged/BrainAccess when provided — never invent a second owner.
    """
    # Lazy-build HybridRetriever from KnowledgeStore when embeddings exist.
    retriever = hybrid_retriever
    if retriever is None and store is not None:
        try:
            from Data.modules.knowledge.retrieval import HybridRetriever

            retriever = HybridRetriever(store)
        except Exception:  # noqa: BLE001
            retriever = None

    if retriever is not None or staged_retriever is not None or brain_access is not None:
        from .trading_brain import adapt_canonical_knowledge

        return adapt_canonical_knowledge(
            knowledge_store=store,
            hybrid_retriever=retriever,
            staged_retriever=staged_retriever,
            brain_access=brain_access,
        )

    class Adapter:
        def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
            if hasattr(store, "search_lexical"):
                rows = store.search_lexical(query, limit=limit)
                out = []
                for row in rows:
                    if isinstance(row, dict):
                        item = dict(row)
                        item.setdefault("retrievalMode", "lexical")
                        item.setdefault("embeddingsSemantic", False)
                        out.append(item)
                    else:
                        out.append(
                            {
                                "document_id": getattr(row, "document_id", None)
                                or getattr(row, "id", None),
                                "title": getattr(row, "title", ""),
                                "content": (getattr(row, "content", "") or "")[:500],
                                "score": getattr(row, "score", 0.0),
                                "retrievalMode": "lexical",
                                "embeddingsSemantic": False,
                            }
                        )
                return out
            return []

    return Adapter()


def attach_trading_brain_adapter(
    facade: BrainFacade,
    *,
    knowledge_store: Any | None = None,
    hybrid_retriever: Any | None = None,
    staged_retriever: Any | None = None,
    brain_access: Any | None = None,
) -> BrainFacade:
    """Replace facade.knowledge with canonical TradingBrainAdapter searcher."""
    facade.knowledge = adapt_knowledge_store(
        knowledge_store,
        hybrid_retriever=hybrid_retriever,
        staged_retriever=staged_retriever,
        brain_access=brain_access,
    )
    return facade


def adapt_memory_store(store: Any) -> MemorySearcher:
    class Adapter:
        def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
            if hasattr(store, "search"):
                rows = store.search(query, limit=limit)
            elif hasattr(store, "list_recent"):
                rows = store.list_recent(limit=limit)
            else:
                return []
            out = []
            for row in rows or []:
                if isinstance(row, dict):
                    out.append(row)
                else:
                    out.append(
                        {
                            "memory_id": getattr(row, "memory_id", None) or getattr(row, "id", None),
                            "content": (getattr(row, "content", "") or "")[:500],
                            "kind": str(getattr(row, "kind", "")),
                        }
                    )
            tokens = [t for t in query.lower().split() if len(t) > 2]
            if tokens and out:
                filtered = [
                    item
                    for item in out
                    if any(t in str(item.get("content", "")).lower() for t in tokens)
                ]
                return filtered[:limit] if filtered else []
            return out[:limit]

    return Adapter()


def adapt_evidence_store(store: Any) -> EvidenceSearcher:
    class Adapter:
        def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
            if hasattr(store, "search"):
                rows = store.search(query, limit=limit)
            elif hasattr(store, "list"):
                rows = store.list(limit=limit)
            else:
                return []
            out = []
            for row in rows or []:
                payload = row.public_dict() if hasattr(row, "public_dict") else dict(row)
                status = str(payload.get("status") or payload.get("verification_status") or "")
                if status and status.upper() in {"UNVERIFIED", "REJECTED", "PENDING"}:
                    continue
                out.append(payload)
            return out[:limit]

    return Adapter()
