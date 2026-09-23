"""Staged retrieval — orchestrates HybridRetriever with progressive cost stages.

HybridRetriever remains the retrieval authority; this module decides *when*
to call it, expand queries, rerank, or deep-recall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from .retrieval import HybridRetriever, RetrievalHit, RetrievalMode, RetrievalQuery

_TOKEN_RE = re.compile(r"[^\W_]{2,}", flags=re.UNICODE)

# Stage A early-exit: short exact-ish queries with a strong lexical hit.
_TRIVIAL_MAX_TOKENS = 6
_TRIVIAL_SCORE = 0.72
_LOW_COVERAGE_HITS = 2
_LOW_COVERAGE_TOP_SCORE = 0.35


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def resolve_use_reranker(
    policy: str | None,
    *,
    reranker_available: bool,
    embedding_is_semantic: bool | None = None,
) -> bool:
    """Map knowledge.rerank_policy → RetrievalQuery.use_reranker.

    Never claims semantic rerank when embeddings are hash-only; ``auto`` still
    may call a cross-encoder if one is wired and available.
    """
    normalized = str(policy or "auto").strip().lower()
    if normalized in {"off", "false", "0", "none"}:
        return False
    if not reranker_available:
        return False
    if normalized == "always":
        return True
    # auto: use when available; hash embeddings do not block cross-encoder rerank
    # but callers must not label the dense path as semantic.
    _ = embedding_is_semantic  # documented honesty hook for callers/traces
    return True


@dataclass
class StageTrace:
    stage: str
    action: str
    detail: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "action": self.action, "detail": dict(self.detail)}


@dataclass
class StagedRetrievalResult:
    hits: list[RetrievalHit]
    stages: list[StageTrace] = field(default_factory=list)
    early_exit: bool = False
    negative_reasons: list[str] = field(default_factory=list)
    expansions: list[str] = field(default_factory=list)
    coverage: str = "unknown"  # high | low | empty | unknown
    rerank_applied: bool = False
    deep_recall_applied: bool = False
    embedding_is_semantic: bool | None = None
    query: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hit_count": len(self.hits),
            "hits": [h.public_dict() if hasattr(h, "public_dict") else {"chunk_id": h.chunk_id} for h in self.hits],
            "stages": [s.public_dict() for s in self.stages],
            "early_exit": self.early_exit,
            "negative_reasons": list(self.negative_reasons),
            "expansions": list(self.expansions),
            "coverage": self.coverage,
            "rerank_applied": self.rerank_applied,
            "deep_recall_applied": self.deep_recall_applied,
            "embedding_is_semantic": self.embedding_is_semantic,
            "truth": {
                "hybrid_retriever_is_authority": True,
                "staged_retriever_orchestrates_only": True,
                "hash_vectors_are_not_semantic_embeddings": self.embedding_is_semantic is False,
            },
        }


class StagedRetriever:
    """Progressive retrieval wrapper around HybridRetriever (+ optional deep recall)."""

    def __init__(
        self,
        retriever: HybridRetriever,
        *,
        deep_recall: Any | None = None,
        rerank_policy: str = "auto",
        early_exit_enabled: bool = True,
    ) -> None:
        self.retriever = retriever
        self.deep_recall = deep_recall
        self.rerank_policy = rerank_policy
        self.early_exit_enabled = early_exit_enabled

    def search(
        self,
        text: str,
        *,
        limit: int = 5,
        conversation_terms: Sequence[str] | None = None,
        source: str | None = None,
        use_deep_recall: bool = False,
        required_precision: str = "normal",
        rerank_policy: str | None = None,
        record_trace: bool = True,
    ) -> StagedRetrievalResult:
        policy = rerank_policy if rerank_policy is not None else self.rerank_policy
        embedding_is_semantic = False
        try:
            embedding_is_semantic = bool(self.retriever._embedding_is_semantic())  # noqa: SLF001
        except Exception:  # noqa: BLE001
            embedding_is_semantic = False

        result = StagedRetrievalResult(
            hits=[],
            query=text,
            embedding_is_semantic=embedding_is_semantic,
        )
        if not (text or "").strip():
            result.negative_reasons.append("empty_query")
            result.coverage = "empty"
            result.stages.append(StageTrace("A", "skip", {"reason": "empty_query"}))
            return result

        # --- Stage A: cheap lexical / conversation-term probe ---
        probe_terms = list(conversation_terms or [])
        probe_query = text
        if probe_terms:
            # Prefer terms that already appear in the query; otherwise append lightly.
            extra = [t for t in probe_terms if t.lower() not in text.lower()][:4]
            if extra:
                probe_query = f"{text} {' '.join(extra)}"

        lexical_probe = self.retriever.search(
            RetrievalQuery(
                text=probe_query,
                limit=min(3, max(1, limit)),
                source=source,
                use_embeddings=False,
                use_reranker=False,
                mode=RetrievalMode.LEXICAL,
                record_trace=record_trace,
            )
        )
        top_score = float(lexical_probe[0].score) if lexical_probe else 0.0
        token_count = len(_tokens(text))
        trivial = (
            self.early_exit_enabled
            and lexical_probe
            and token_count <= _TRIVIAL_MAX_TOKENS
            and top_score >= _TRIVIAL_SCORE
            and self._phrase_overlap(text, lexical_probe[0].content) >= 0.5
        )
        result.stages.append(
            StageTrace(
                "A",
                "early_exit" if trivial else "probe",
                {
                    "probe_hits": len(lexical_probe),
                    "top_score": round(top_score, 4),
                    "token_count": token_count,
                    "conversation_terms": list(probe_terms)[:8],
                },
            )
        )
        if trivial:
            result.hits = lexical_probe[:limit]
            result.early_exit = True
            result.coverage = "high"
            return result

        # --- Stage B: hybrid retrieval ---
        reranker_available = bool(
            self.retriever.reranker is not None
            and hasattr(self.retriever.reranker, "available")
            and self.retriever.reranker.available()
        )
        # Rerank deferred to Stage D unless policy is always (hybrid_rerank mode).
        use_rerank_now = False
        hybrid_hits = self.retriever.search(
            RetrievalQuery(
                text=text,
                limit=limit,
                source=source,
                use_embeddings=True,
                use_reranker=use_rerank_now,
                mode=RetrievalMode.HYBRID,
                record_trace=record_trace,
            )
        )
        result.hits = list(hybrid_hits)
        result.stages.append(
            StageTrace(
                "B",
                "hybrid",
                {
                    "hits": len(hybrid_hits),
                    "top_score": round(float(hybrid_hits[0].score), 4) if hybrid_hits else 0.0,
                    "embedding_is_semantic": embedding_is_semantic,
                },
            )
        )

        coverage = self._coverage(result.hits, limit=limit)
        result.coverage = coverage

        # --- Stage C: query expansion only if coverage low ---
        if coverage == "low":
            expansions = self._simple_expansions(text, conversation_terms=probe_terms)
            result.expansions = expansions
            expanded_hits: list[RetrievalHit] = list(result.hits)
            seen = {h.chunk_id for h in expanded_hits}
            for expansion in expansions[1:]:  # skip original (already searched)
                more = self.retriever.search(
                    RetrievalQuery(
                        text=expansion,
                        limit=limit,
                        source=source,
                        use_embeddings=True,
                        use_reranker=False,
                        mode=RetrievalMode.HYBRID,
                        record_trace=record_trace,
                    )
                )
                for hit in more:
                    if hit.chunk_id not in seen:
                        expanded_hits.append(hit)
                        seen.add(hit.chunk_id)
            expanded_hits.sort(key=lambda h: h.score, reverse=True)
            result.hits = expanded_hits[: max(limit * 2, limit)]
            result.coverage = self._coverage(result.hits, limit=limit)
            result.stages.append(
                StageTrace(
                    "C",
                    "expand",
                    {
                        "expansions": expansions,
                        "hits_after": len(result.hits),
                        "coverage": result.coverage,
                    },
                )
            )
        else:
            result.stages.append(
                StageTrace("C", "skip", {"reason": f"coverage_{coverage}"})
            )

        # --- Stage D: rerank per policy ---
        want_rerank = resolve_use_reranker(
            policy,
            reranker_available=reranker_available,
            embedding_is_semantic=embedding_is_semantic,
        )
        # auto: only when coverage was low or always when policy=always
        if policy and str(policy).lower() == "auto" and result.coverage == "high" and not result.early_exit:
            # Still allow auto rerank when we have candidates; prefer when not high-confidence trivial.
            want_rerank = want_rerank and bool(result.hits) and result.coverage != "empty"
        if want_rerank and result.hits:
            reranked = self.retriever.search(
                RetrievalQuery(
                    text=text,
                    limit=limit,
                    source=source,
                    use_embeddings=True,
                    use_reranker=True,
                    mode=RetrievalMode.HYBRID_RERANK,
                    record_trace=record_trace,
                )
            )
            if reranked:
                result.hits = reranked[:limit]
                result.rerank_applied = True
                result.stages.append(
                    StageTrace(
                        "D",
                        "rerank",
                        {
                            "policy": policy,
                            "embedding_is_semantic": embedding_is_semantic,
                            "reranker_available": reranker_available,
                        },
                    )
                )
            else:
                result.stages.append(
                    StageTrace("D", "skip", {"reason": "rerank_empty"})
                )
        else:
            result.stages.append(
                StageTrace(
                    "D",
                    "skip",
                    {
                        "reason": "policy_or_unavailable",
                        "policy": policy,
                        "reranker_available": reranker_available,
                    },
                )
            )

        # Trim to requested limit after optional expansion.
        result.hits = result.hits[:limit]
        result.coverage = self._coverage(result.hits, limit=limit)

        # --- Stage E: deep recall when enabled and precision/low coverage ---
        need_deep = bool(use_deep_recall) and (
            required_precision == "high" or result.coverage in {"low", "empty"}
        )
        if need_deep and self.deep_recall is not None and getattr(self.deep_recall, "enabled", True):
            try:
                from .deep_recall import DeepRecallRequest

                dr = self.deep_recall.recall(
                    DeepRecallRequest(
                        current_question=text,
                        required_precision=required_precision,
                        hydrate_limit=limit,
                    )
                )
                result.deep_recall_applied = True
                # Merge exact details as soft hits only when hybrid coverage was weak.
                if result.coverage in {"low", "empty"} and getattr(dr, "exact_details", None):
                    for detail in list(dr.exact_details)[:limit]:
                        if not isinstance(detail, dict):
                            continue
                        content = str(detail.get("content") or "")
                        if not content:
                            continue
                        result.hits.append(
                            RetrievalHit(
                                document_id=str(detail.get("document_id") or detail.get("ref") or "deep_recall"),
                                chunk_id=str(detail.get("chunk_id") or detail.get("ref") or "deep_recall"),
                                chunk_index=0,
                                title=str(detail.get("title") or "deep_recall"),
                                source="deep_recall",
                                content=content,
                                score=float(detail.get("score") or 0.3),
                                modality="deep_recall",
                                original_path=detail.get("original_path"),
                                document_hash=detail.get("content_hash") or detail.get("document_hash"),
                                chunk_hash=str(detail.get("chunk_hash") or detail.get("chunk_id") or "deep_recall"),
                                provenance={"stage": "E", "deep_recall": True},
                            )
                        )
                    result.hits = result.hits[:limit]
                    result.coverage = self._coverage(result.hits, limit=limit)
                result.stages.append(
                    StageTrace(
                        "E",
                        "deep_recall",
                        {
                            "available": getattr(dr, "available", False),
                            "stopped_reason": getattr(dr, "stopped_reason", ""),
                            "context_cost": getattr(dr, "context_cost", 0),
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                result.negative_reasons.append(f"deep_recall_error:{type(exc).__name__}")
                result.stages.append(
                    StageTrace("E", "error", {"error": type(exc).__name__})
                )
        else:
            result.stages.append(
                StageTrace(
                    "E",
                    "skip",
                    {
                        "use_deep_recall": use_deep_recall,
                        "need_deep": need_deep,
                        "deep_recall_wired": self.deep_recall is not None,
                    },
                )
            )

        if not result.hits:
            result.negative_reasons.append("no_hits_after_stages")
            result.coverage = "empty"
        return result

    @staticmethod
    def _coverage(hits: Sequence[RetrievalHit], *, limit: int) -> str:
        if not hits:
            return "empty"
        top = float(hits[0].score) if hits else 0.0
        if len(hits) >= min(limit, _LOW_COVERAGE_HITS + 1) and top >= _LOW_COVERAGE_TOP_SCORE:
            return "high"
        if len(hits) <= _LOW_COVERAGE_HITS or top < _LOW_COVERAGE_TOP_SCORE:
            return "low"
        return "high"

    @staticmethod
    def _phrase_overlap(query: str, content: str) -> float:
        q_tokens = set(_tokens(query))
        if not q_tokens:
            return 0.0
        c_tokens = set(_tokens(content))
        return len(q_tokens & c_tokens) / len(q_tokens)

    @staticmethod
    def _simple_expansions(
        text: str,
        *,
        conversation_terms: Sequence[str] | None = None,
    ) -> list[str]:
        """Generate cheap expansions: original, entity-ish tokens, exact phrase."""
        original = (text or "").strip()
        toks = _tokens(original)
        # Entity-ish: longer tokens / capitalized-looking originals preserved via length.
        entity_ish = [t for t in toks if len(t) >= 4][:8]
        expansions = [original]
        if entity_ish:
            expansions.append(" ".join(entity_ish))
        # Exact: quoted form of the original (helps lexical FTS phrase-ish matching).
        if " " in original:
            expansions.append(f'"{original}"')
        for term in conversation_terms or []:
            term_s = str(term).strip()
            if term_s and term_s.lower() not in original.lower():
                expansions.append(f"{original} {term_s}")
                break
        # Deduplicate while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for item in expansions:
            key = item.lower()
            if key in seen or not item.strip():
                continue
            seen.add(key)
            out.append(item)
        return out
