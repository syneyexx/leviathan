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
    # StrategyMemory provenance (advisory — never authority over RiskGuard).
    strategy_id: str | None = None
    strategy_version: int | None = None
    rejected: bool | None = None
    origin: str | None = None
    epistemic_state: str | None = None
    validation_stage: str | None = None
    contradictory: bool = False

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
            "strategyId": self.strategy_id,
            "strategyVersion": self.strategy_version,
            "rejected": self.rejected,
            "origin": self.origin,
            "epistemicState": self.epistemic_state,
            "validationStage": self.validation_stage,
            "contradictory": self.contradictory,
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
        strategy_memory_lister: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        self.brain_access = brain_access
        self.hybrid_retriever = hybrid_retriever
        self.staged_retriever = staged_retriever
        self.knowledge_store = knowledge_store
        self.memory_search = memory_search
        self.evidence_search = evidence_search
        self.neuro_assess = neuro_assess
        # StrategyMemory is experience evidence — advisory only; never execution authority.
        self.strategy_memory_lister = strategy_memory_lister

    def retrieve(
        self,
        request: TradingRetrievalRequest,
        *,
        firewall: EpistemicFirewall | None = None,
        prefer_negative: bool = False,
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

        # StrategyMemory (successes + failures) — PIT via available_at / decision_as_of.
        strategy_hits = self._strategy_memory_hits(request, limit=limit, prefer_negative=prefer_negative)
        if strategy_hits:
            notes.append(f"strategy_memory_hits={len(strategy_hits)}")
            hits.extend(strategy_hits)

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

        if prefer_negative:
            hits.sort(key=lambda h: (0 if h.rejected or h.contradictory else 1, -(h.score or 0.0)))

        return TradingRetrievalResult(
            hits=hits[:limit],
            retrieval_mode=mode,
            embeddings_semantic=semantic,
            notes=notes,
            miss=len(hits) == 0,
            request=request.public_dict(),
        )

    def _strategy_memory_hits(
        self,
        request: TradingRetrievalRequest,
        *,
        limit: int,
        prefer_negative: bool = False,
    ) -> list[TradingRetrievalHit]:
        if self.strategy_memory_lister is None:
            return []
        try:
            rows = self.strategy_memory_lister(
                as_of_ts=request.decision_as_of,
                strategy_id=None,
                limit=max(limit * 4, 24),
            )
        except TypeError:
            try:
                rows = self.strategy_memory_lister(  # type: ignore[misc]
                    request.decision_as_of, max(limit * 4, 24)
                )
            except Exception:  # noqa: BLE001
                return []
        except Exception:  # noqa: BLE001
            return []

        query_tokens = {
            t.lower()
            for t in (request.query + " " + (request.regime or "") + " " + (request.strategy_family or "")).split()
            if len(t) > 2
        }
        scored: list[tuple[float, TradingRetrievalHit]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            # SEALED / non-adaptive evidence is an epistemic sink — never adaptive
            # discovery retrieval. Critic/risk/postmortem prefer_negative may still
            # surface REJECTED non-sealed lessons as negative experience.
            from .epistemic import EvidenceClass, is_adaptive_evidence

            meta_row = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            applicability = row.get("applicability") if isinstance(row.get("applicability"), dict) else {}
            evidence_class = (
                meta_row.get("evidence_class")
                or applicability.get("evidence_class")
                or meta_row.get("validation_stage")
                or meta_row.get("split_role")
            )
            stage = str(meta_row.get("validation_stage") or "") or None
            split = str(meta_row.get("split_role") or meta_row.get("validation_stage") or "") or None
            ec_text = str(evidence_class) if evidence_class is not None else None
            sealed_markers = {
                EvidenceClass.SEALED_QUALIFICATION_EVIDENCE.value,
                "SEALED",
                "sealed",
                "SEALED_TEST",
                "sealed_test",
                "SEALED_EVALUATION",
            }
            is_sealed = any(
                (raw or "").strip().upper() in {m.upper() for m in sealed_markers}
                for raw in (ec_text, stage, split)
            )
            adaptive_ok = is_adaptive_evidence(
                evidence_class=ec_text,
                validation_stage=stage,
                split_role=split,
            )
            rejected_row = bool(row.get("rejected"))
            if not adaptive_ok:
                if not (prefer_negative and rejected_row and not is_sealed):
                    continue
            if applicability.get("adaptive") is False and not (
                prefer_negative and rejected_row and not is_sealed
            ):
                continue
            hit = strategy_memory_to_hit(row, mode="strategy_memory")
            blob = " ".join(
                [
                    str(hit.content_excerpt or ""),
                    str(hit.title or ""),
                    str((row.get("features") or {})),
                    str((row.get("applicability") or {})),
                    str((row.get("outcome_summary") or "")),
                ]
            ).lower()
            score = 0.0
            for tok in query_tokens:
                if tok in blob:
                    score += 1.0
            if request.regime and str(request.regime).lower() in blob:
                score += 2.0
            if prefer_negative and (hit.rejected or hit.contradictory):
                score += 3.0
            hit.score = score
            scored.append((score, hit))
        scored.sort(key=lambda x: -x[0])
        # Keep zero-score rejected memories when prefer_negative (negative results are first-class).
        out: list[TradingRetrievalHit] = []
        for score, hit in scored:
            if score > 0 or (prefer_negative and (hit.rejected or hit.contradictory)):
                out.append(hit)
            if len(out) >= limit:
                break
        return out


def strategy_memory_to_hit(row: dict[str, Any], *, mode: str = "strategy_memory") -> TradingRetrievalHit:
    """Map a durable StrategyMemory row into an advisory TradingRetrievalHit."""
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    rejected = bool(row.get("rejected"))
    origin = str(meta.get("origin") or row.get("origin") or "strategy_memory")
    epistemic = str(
        meta.get("epistemic_state")
        or meta.get("epistemicState")
        or ("REJECTED" if rejected else "MEASURED")
    )
    stage = meta.get("validation_stage") or meta.get("validationStage") or meta.get("split_role")
    summary = str(row.get("outcome_summary") or "")
    features = row.get("features") if isinstance(row.get("features"), dict) else {}
    applicability = row.get("applicability") if isinstance(row.get("applicability"), dict) else {}
    title = f"strategy_memory:{row.get('strategy_id')}:v{row.get('strategy_version')}"
    if rejected:
        title = f"REJECTED:{title}"
    excerpt_parts = [summary]
    if features:
        excerpt_parts.append(f"features={features}")
    if applicability:
        excerpt_parts.append(f"applicability={applicability}")
    mid = str(row.get("memory_id") or "")
    return TradingRetrievalHit(
        source_kind="strategy_memory",
        document_id=mid or None,
        title=title,
        content_excerpt=" | ".join(excerpt_parts)[:800],
        available_at=row.get("available_at"),
        published_at=row.get("created_at"),
        trust="strategy_memory",
        evidence_refs=[mid] if mid else [],
        retrieval_mode=mode,
        embeddings_semantic=False,
        strategy_id=str(row.get("strategy_id") or "") or None,
        strategy_version=int(row["strategy_version"]) if row.get("strategy_version") is not None else None,
        rejected=rejected,
        origin=origin,
        epistemic_state=epistemic,
        validation_stage=str(stage) if stage is not None else None,
        contradictory=rejected or epistemic.upper() in {"REJECTED", "NEGATIVE", "FAILED"},
        score=1.0 if rejected else 0.5,
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
    strategy_memory_lister: Callable[..., list[dict[str, Any]]] | None = None,
) -> KnowledgeSearcher:
    """KnowledgeSearcher that uses canonical Brain/Knowledge stack when available."""

    adapter = TradingBrainAdapter(
        brain_access=brain_access,
        hybrid_retriever=hybrid_retriever,
        staged_retriever=staged_retriever,
        knowledge_store=knowledge_store,
        strategy_memory_lister=strategy_memory_lister,
    )

    class Adapter:
        trading_adapter = adapter

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
