"""Trading Brain adapter — maps trading requests onto canonical Brain/Knowledge.

Does NOT own retrieval. Canonical owners remain:
  BrainAccessFacade / HybridRetriever / StagedRetriever / KnowledgeStore /
  Memory / Evidence / Neuro.

MarketSim keeps BrainFacade as the trading-side advisory hook + epistemic filter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .brain_hooks import BrainRetrieval, KnowledgeSearcher
from .epistemic import EpistemicFirewall, filter_hits_for_as_of


@dataclass
class TradingRetrievalRequest:
    """Adapter-level trading retrieval request → canonical Brain/Knowledge."""

    query: str
    role: str | None = None
    instrument_ids: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    asset_classes: list[str] = field(default_factory=list)
    venue: str | None = None
    timeframes: list[str] = field(default_factory=list)
    regime: str | None = None
    objective: str | None = None
    strategy_family: str | None = None
    decision_as_of: str | None = None
    knowledge_domains: list[str] = field(default_factory=list)
    dataset_ids: list[str] = field(default_factory=list)
    max_hits: int = 5
    trust_requirements: list[str] = field(default_factory=list)
    prefer_semantic: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "role": self.role,
            "instrumentIds": list(self.instrument_ids),
            "symbols": list(self.symbols),
            "assetClasses": list(self.asset_classes),
            "venue": self.venue,
            "timeframes": list(self.timeframes),
            "regime": self.regime,
            "objective": self.objective,
            "strategyFamily": self.strategy_family,
            "decisionAsOf": self.decision_as_of,
            "knowledgeDomains": list(self.knowledge_domains),
            "datasetIds": list(self.dataset_ids),
            "maxHits": self.max_hits,
            "trustRequirements": list(self.trust_requirements),
            "preferSemantic": self.prefer_semantic,
        }

    def expanded_query(self) -> str:
        parts = [self.query.strip()]
        if self.objective:
            parts.append(str(self.objective))
        if self.regime:
            parts.append(f"regime:{self.regime}")
        if self.strategy_family:
            parts.append(f"strategy:{self.strategy_family}")
        for sym in self.symbols[:8]:
            parts.append(str(sym))
        for ac in self.asset_classes[:4]:
            parts.append(str(ac))
        for tf in self.timeframes[:4]:
            parts.append(str(tf))
        return " ".join(p for p in parts if p)


@dataclass
class TradingRetrievalHit:
    source_kind: str
    document_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    rerank_score: float | None = None
    title: str = ""
    content_excerpt: str = ""
    published_at: str | None = None
    available_at: str | None = None
    trust: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    retrieval_mode: str = "lexical"
    embeddings_semantic: bool | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "sourceKind": self.source_kind,
            "documentId": self.document_id,
            "datasetId": self.dataset_id,
            "datasetVersion": self.dataset_version,
            "chunkId": self.chunk_id,
            "score": self.score,
            "rerankScore": self.rerank_score,
            "title": self.title,
            "contentExcerpt": self.content_excerpt,
            "publishedAt": self.published_at,
            "availableAt": self.available_at,
            "trust": self.trust,
            "evidenceRefs": list(self.evidence_refs),
            "retrievalMode": self.retrieval_mode,
            "embeddingsSemantic": self.embeddings_semantic,
            # Compatibility keys for epistemic firewall / BrainFacade hits.
            "source": self.source_kind,
            "document_id": self.document_id,
            "content": self.content_excerpt,
            "available_at": self.available_at,
            "published_at": self.published_at,
        }


@dataclass
class TradingRetrievalResult:
    hits: list[TradingRetrievalHit] = field(default_factory=list)
    retrieval_mode: str = "lexical"
    embeddings_semantic: bool | None = None
    notes: list[str] = field(default_factory=list)
    miss: bool = True
    request: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "hits": [h.public_dict() for h in self.hits],
            "retrievalMode": self.retrieval_mode,
            "embeddingsSemantic": self.embeddings_semantic,
            "notes": list(self.notes),
            "miss": self.miss,
            "request": dict(self.request),
            "truth": {
                "brain_is_advisory": True,
                "canonical_brain_owner": True,
                "no_second_retrieval_authority": True,
                "hash_embeddings_are_not_semantic": self.embeddings_semantic is False,
                "lexical_mode_reported_honestly": self.retrieval_mode == "lexical"
                or self.embeddings_semantic is False,
            },
        }

    def as_brain_retrieval(self) -> BrainRetrieval:
        return BrainRetrieval(
            hits=[h.public_dict() for h in self.hits],
            miss=self.miss,
            notes=list(self.notes)
            + [
                f"retrieval_mode={self.retrieval_mode}",
                f"embeddings_semantic={self.embeddings_semantic}",
            ],
        )


class TradingBrainAdapter:
    """Trading-specific request mapping over canonical Brain/Knowledge retrieval."""

    def __init__(
        self,
        *,
        brain_access: Any | None = None,
        hybrid_retriever: Any | None = None,
        staged_retriever: Any | None = None,
        knowledge_store: Any | None = None,
        memory_search: Callable[..., list[Any]] | None = None,
        evidence_search: Callable[..., list[Any]] | None = None,
        neuro_assess: Callable[[str], Any] | None = None,
    ) -> None:
        self.brain_access = brain_access
        self.hybrid_retriever = hybrid_retriever
        self.staged_retriever = staged_retriever
        self.knowledge_store = knowledge_store
        self.memory_search = memory_search
        self.evidence_search = evidence_search
        self.neuro_assess = neuro_assess

    def retrieve(
        self,
        request: TradingRetrievalRequest,
        *,
        firewall: EpistemicFirewall | None = None,
    ) -> TradingRetrievalResult:
        notes: list[str] = []
        mode = "lexical"
        semantic: bool | None = None
        hits: list[TradingRetrievalHit] = []

        query = request.expanded_query()
        limit = max(1, min(int(request.max_hits), 20))

        # Prefer StagedRetriever → HybridRetriever → BrainAccess → lexical KnowledgeStore.
        if self.staged_retriever is not None and hasattr(self.staged_retriever, "search"):
            try:
                from Data.modules.knowledge.retrieval import RetrievalQuery

                rq = RetrievalQuery(
                    text=query,
                    limit=limit,
                    use_embeddings=bool(request.prefer_semantic),
                )
                staged = self.staged_retriever.search(rq)
                semantic = getattr(staged, "embedding_is_semantic", None)
                mode = "semantic" if semantic else "lexical"
                if semantic is False:
                    notes.append("staged_retriever_lexical_or_non_semantic_embeddings")
                for hit in list(getattr(staged, "hits", None) or [])[:limit]:
                    hits.append(_hit_from_retrieval_hit(hit, mode=mode, semantic=semantic))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"staged_retriever_error:{exc}")

        if not hits and self.hybrid_retriever is not None and hasattr(self.hybrid_retriever, "search"):
            try:
                from Data.modules.knowledge.retrieval import RetrievalQuery

                rq = RetrievalQuery(
                    text=query,
                    limit=limit,
                    use_embeddings=bool(request.prefer_semantic),
                )
                rows = self.hybrid_retriever.search(rq)
                # HybridRetriever may expose embedding honesty.
                emb = getattr(self.hybrid_retriever, "embedding_provider", None)
                if emb is not None and hasattr(emb, "is_semantic"):
                    semantic = bool(emb.is_semantic)
                elif hasattr(self.hybrid_retriever, "_embedding_is_semantic"):
                    try:
                        semantic = bool(self.hybrid_retriever._embedding_is_semantic())  # noqa: SLF001
                    except Exception:  # noqa: BLE001
                        semantic = False
                else:
                    semantic = False
                mode = "hybrid_semantic" if semantic else "lexical"
                if not semantic:
                    notes.append("hybrid_retriever_non_semantic_or_lexical_only")
                for hit in list(rows or [])[:limit]:
                    hits.append(_hit_from_retrieval_hit(hit, mode=mode, semantic=semantic))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"hybrid_retriever_error:{exc}")

        if not hits and self.brain_access is not None and hasattr(self.brain_access, "gather"):
            try:
                from Data.modules.brain.contracts import BrainContextRequest

                ctx_req = BrainContextRequest(
                    goal=request.objective or request.query,
                    queries=[query],
                    role=request.role or "trading",
                    domain="trading",
                    symbols=list(request.symbols)[:12],
                    result_limits={"knowledge": limit, "memory": 2, "evidence": 2},
                    include_evidence=True,
                    include_experience=False,
                )
                ctx = self.brain_access.gather(ctx_req)
                mode = "brain_access"
                semantic = None
                notes.append("via_brain_access_facade")
                for ref in list(getattr(ctx, "knowledge", None) or [])[:limit]:
                    hits.append(
                        TradingRetrievalHit(
                            source_kind="knowledge",
                            document_id=getattr(ref, "ref_id", None),
                            title=getattr(ref, "title", "") or "",
                            content_excerpt=(getattr(ref, "excerpt", "") or "")[:800],
                            score=getattr(ref, "score", None),
                            trust=getattr(ref, "trust", None),
                            retrieval_mode=mode,
                            embeddings_semantic=semantic,
                            dataset_id=(getattr(ref, "metadata", {}) or {}).get("dataset_id")
                            if isinstance(getattr(ref, "metadata", None), dict)
                            else None,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"brain_access_error:{exc}")

        if not hits and self.knowledge_store is not None and hasattr(self.knowledge_store, "search_lexical"):
            try:
                rows = self.knowledge_store.search_lexical(query, limit=limit)
                mode = "lexical"
                semantic = False
                notes.append("fallback_knowledge_lexical")
                for row in rows or []:
                    hits.append(_hit_from_row(row, mode=mode, semantic=False))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"lexical_error:{exc}")

        # Optional memory / evidence enrichment (advisory).
        if self.memory_search is not None:
            try:
                for row in self.memory_search(query, limit=2) or []:
                    hits.append(_hit_from_row(row, mode=mode, semantic=semantic, source_kind="memory"))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"memory_error:{exc}")

        # Temporal firewall — fail-closed for missing timestamps on time-sensitive content.
        boundary = request.decision_as_of
        if firewall is not None:
            boundary = firewall.as_of
        if boundary:
            raw_hits = [h.public_dict() for h in hits]
            kept_dicts, receipts = filter_hits_for_as_of(
                raw_hits,
                as_of=str(boundary),
                time_sensitive_default=True,
                allow_timeless_reference=True,
                firewall=firewall,
            )
            # Rehydrate TradingRetrievalHit from filtered dicts (bounded fields only).
            by_id = {
                (h.document_id, h.content_excerpt[:80]): h for h in hits
            }
            filtered: list[TradingRetrievalHit] = []
            for d in kept_dicts:
                if str(d.get("source") or "") == "neuro":
                    continue
                key = (d.get("documentId") or d.get("document_id"), str(d.get("contentExcerpt") or d.get("content") or "")[:80])
                existing = by_id.get(key)
                if existing is not None:
                    filtered.append(existing)
                else:
                    filtered.append(_hit_from_row(d, mode=mode, semantic=semantic))
            hits = filtered
            if receipts:
                notes.append(f"as_of_filter_dropped_{len(receipts)}")
                notes.append(
                    "leakage_receipts="
                    + str([r.public_dict() for r in receipts[:12]])
                )

        return TradingRetrievalResult(
            hits=hits[:limit],
            retrieval_mode=mode,
            embeddings_semantic=semantic,
            notes=notes,
            miss=len(hits) == 0,
            request=request.public_dict(),
        )


def _hit_from_retrieval_hit(hit: Any, *, mode: str, semantic: bool | None) -> TradingRetrievalHit:
    if hasattr(hit, "public_dict"):
        d = hit.public_dict()
    elif isinstance(hit, dict):
        d = hit
    else:
        d = {
            "document_id": getattr(hit, "document_id", None),
            "chunk_id": getattr(hit, "chunk_id", None),
            "title": getattr(hit, "title", ""),
            "content": getattr(hit, "content", "") or getattr(hit, "text", ""),
            "score": getattr(hit, "score", None),
            "rerank_score": getattr(hit, "rerank_score", None),
            "source": getattr(hit, "source", "knowledge"),
            "metadata": getattr(hit, "metadata", {}) or {},
        }
    meta = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
    content = str(d.get("content") or d.get("excerpt") or d.get("text") or "")[:800]
    return TradingRetrievalHit(
        source_kind=str(d.get("source") or d.get("source_kind") or "knowledge"),
        document_id=d.get("document_id") or d.get("documentId") or meta.get("document_id"),
        dataset_id=meta.get("dataset_id") or meta.get("datasetId") or d.get("dataset_id"),
        dataset_version=meta.get("dataset_version") or meta.get("version_id"),
        chunk_id=d.get("chunk_id") or d.get("chunkId"),
        score=float(d["score"]) if d.get("score") is not None else None,
        rerank_score=float(d["rerank_score"]) if d.get("rerank_score") is not None else None,
        title=str(d.get("title") or ""),
        content_excerpt=content,
        published_at=meta.get("published_at") or d.get("published_at"),
        available_at=meta.get("available_at") or d.get("available_at"),
        trust=str(meta.get("trust") or d.get("trust") or "knowledge"),
        evidence_refs=list(meta.get("evidence_refs") or []),
        retrieval_mode=mode,
        embeddings_semantic=semantic,
    )


def _hit_from_row(
    row: Any,
    *,
    mode: str,
    semantic: bool | None,
    source_kind: str = "knowledge",
) -> TradingRetrievalHit:
    if isinstance(row, dict):
        content = str(
            row.get("content")
            or row.get("text")
            or row.get("chunk_content")
            or row.get("document_content")
            or row.get("contentExcerpt")
            or ""
        )[:800]
        return TradingRetrievalHit(
            source_kind=source_kind,
            document_id=row.get("document_id") or row.get("id") or row.get("memory_id"),
            title=str(row.get("title") or ""),
            content_excerpt=content,
            score=float(row["score"]) if row.get("score") is not None else (
                float(row["rank"]) if row.get("rank") is not None else None
            ),
            published_at=row.get("published_at"),
            available_at=row.get("available_at"),
            trust=str(row.get("trust") or source_kind),
            retrieval_mode=mode,
            embeddings_semantic=semantic,
            dataset_id=row.get("dataset_id"),
            chunk_id=row.get("chunk_id"),
        )
    return TradingRetrievalHit(
        source_kind=source_kind,
        document_id=getattr(row, "document_id", None) or getattr(row, "id", None),
        title=str(getattr(row, "title", "") or ""),
        content_excerpt=str(
            getattr(row, "content", None)
            or getattr(row, "chunk_content", None)
            or ""
        )[:800],
        score=getattr(row, "score", None),
        retrieval_mode=mode,
        embeddings_semantic=semantic,
    )


def adapt_canonical_knowledge(
    *,
    knowledge_store: Any | None = None,
    hybrid_retriever: Any | None = None,
    staged_retriever: Any | None = None,
    brain_access: Any | None = None,
) -> KnowledgeSearcher:
    """KnowledgeSearcher that uses canonical Brain/Knowledge stack when available."""

    adapter = TradingBrainAdapter(
        brain_access=brain_access,
        hybrid_retriever=hybrid_retriever,
        staged_retriever=staged_retriever,
        knowledge_store=knowledge_store,
    )

    class Adapter:
        def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
            result = adapter.retrieve(
                TradingRetrievalRequest(query=query, max_hits=limit, prefer_semantic=True)
            )
            return [h.public_dict() for h in result.hits]

        def retrieve_trading(
            self, request: TradingRetrievalRequest, *, firewall: EpistemicFirewall | None = None
        ) -> TradingRetrievalResult:
            return adapter.retrieve(request, firewall=firewall)

    return Adapter()
