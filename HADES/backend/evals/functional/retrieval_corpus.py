"""Retrieval evaluation corpus + metrics (Recall@K, Precision@K, MRR, nDCG).

Documents are synthetic fixtures labeled as such. Never leak held-out answers
into production ranking code.
"""

from __future__ import annotations

import math
from typing import Any

RETRIEVAL_CORPUS_VERSION = "retrieval_corpus_v1"

# Synthetic document store: id → {text, store, lang, stale, tags}
DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "k_rag_en",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "Retrieval-augmented generation combines lexical search with optional embeddings.",
        "tags": ["rag", "retrieval"],
    },
    {
        "id": "k_rag_nl",
        "store": "knowledge",
        "lang": "nl",
        "stale": False,
        "text": "Retrieval-augmented generation combineert lexicale zoekopdrachten met optionele embeddings.",
        "tags": ["rag", "retrieval"],
    },
    {
        "id": "k_memory_vs_knowledge",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "Memory is personal preferences; Knowledge is curated facts; Evidence is cited sources.",
        "tags": ["stores"],
    },
    {
        "id": "m_pref_nl",
        "store": "memory",
        "lang": "nl",
        "stale": False,
        "text": "Gebruiker prefereert antwoorden in het Nederlands met korte zinnen.",
        "tags": ["preference"],
    },
    {
        "id": "e_latency_a",
        "store": "evidence",
        "lang": "en",
        "stale": False,
        "text": "Claim A: p95 latency improved by 50% after indexing.",
        "tags": ["latency", "contradict"],
    },
    {
        "id": "e_latency_b",
        "store": "evidence",
        "lang": "en",
        "stale": False,
        "text": "Claim B: p95 latency worsened after indexing.",
        "tags": ["latency", "contradict"],
    },
    {
        "id": "k_stale_api",
        "store": "knowledge",
        "lang": "en",
        "stale": True,
        "text": "The Chat API path is /api/v1/legacy-chat (DEPRECATED 2024).",
        "tags": ["api", "stale"],
    },
    {
        "id": "k_current_api",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "The Chat API path is POST /api/conversations/{id}/messages.",
        "tags": ["api", "current"],
    },
    {
        "id": "k_keyword_spam",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "retrieval retrieval retrieval retrieval banana pudding recipe unrelated filler.",
        "tags": ["distractor"],
    },
    {
        "id": "k_coding_worktree",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "HADES coding agent uses git worktrees, patch apply, and hidden acceptance tests.",
        "tags": ["coding"],
    },
    {
        "id": "k_dup_a",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "Hybrid ranking blends lexical and semantic scores with configurable weights.",
        "tags": ["hybrid", "dup"],
    },
    {
        "id": "k_dup_b",
        "store": "knowledge",
        "lang": "en",
        "stale": False,
        "text": "Hybrid ranking blends lexical and semantic scores with configurable weights.",
        "tags": ["hybrid", "dup"],
    },
]

# Queries with relevant doc ids (judge-side only)
QUERIES: list[dict[str, Any]] = [
    {
        "id": "q_exact_lexical",
        "text": "Retrieval-augmented generation combines lexical search",
        "relevant": ["k_rag_en"],
        "split": "regression",
        "tags": ["exact"],
    },
    {
        "id": "q_paraphrase",
        "text": "How does RAG mix keyword lookup with vectors?",
        "relevant": ["k_rag_en", "k_rag_nl"],
        "split": "dev",
        "tags": ["paraphrase", "semantic"],
    },
    {
        "id": "q_nl_to_en",
        "text": "Wat is retrieval-augmented generation?",
        "relevant": ["k_rag_en", "k_rag_nl"],
        "split": "regression",
        "tags": ["cross_lang", "nl_query"],
    },
    {
        "id": "q_en_to_nl",
        "text": "How does Dutch documentation describe RAG embeddings?",
        "relevant": ["k_rag_nl", "k_rag_en"],
        "split": "dev",
        "tags": ["cross_lang", "en_query"],
    },
    {
        "id": "q_store_memory",
        "text": "What language preference does the user have?",
        "relevant": ["m_pref_nl"],
        "wrong_store_if": ["knowledge", "evidence"],
        "split": "regression",
        "tags": ["store_separation"],
    },
    {
        "id": "q_store_knowledge",
        "text": "Difference between Memory Knowledge and Evidence",
        "relevant": ["k_memory_vs_knowledge"],
        "split": "dev",
        "tags": ["store_separation"],
    },
    {
        "id": "q_contradict",
        "text": "Did latency improve after indexing?",
        "relevant": ["e_latency_a", "e_latency_b"],
        "split": "dev",
        "tags": ["contradict"],
    },
    {
        "id": "q_freshness",
        "text": "What is the current Chat API path?",
        "relevant": ["k_current_api"],
        "stale_ids": ["k_stale_api"],
        "split": "regression",
        "tags": ["freshness"],
    },
    {
        "id": "q_distractor",
        "text": "Explain hybrid lexical semantic ranking weights",
        "relevant": ["k_dup_a", "k_dup_b"],
        "split": "dev",
        "tags": ["distractor"],
    },
    {
        "id": "q_coding",
        "text": "How does the coding agent isolate repository edits?",
        "relevant": ["k_coding_worktree"],
        "split": "dev",
        "tags": ["coding"],
    },
    # Expand toward 30+
    {
        "id": "q_multi_hop_stores",
        "text": "Where should personal Dutch preference live versus curated RAG facts?",
        "relevant": ["m_pref_nl", "k_memory_vs_knowledge", "k_rag_en"],
        "split": "held_out",
        "tags": ["multi_hop"],
    },
    {
        "id": "q_spam_resist",
        "text": "banana pudding",
        "relevant": ["k_keyword_spam"],
        "split": "dev",
        "tags": ["keyword_density"],
    },
]


def recall_at_k(relevant: set[str], ranked_ids: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    hit = sum(1 for doc_id in ranked_ids[:k] if doc_id in relevant)
    return hit / len(relevant)


def precision_at_k(relevant: set[str], ranked_ids: list[str], k: int) -> float:
    top = ranked_ids[:k]
    if not top:
        return 0.0
    hit = sum(1 for doc_id in top if doc_id in relevant)
    return hit / len(top)


def mrr(relevant: set[str], ranked_ids: list[str]) -> float:
    for i, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(relevant: set[str], ranked_ids: list[str], k: int) -> float:
    def dcg(ids: list[str]) -> float:
        score = 0.0
        for i, doc_id in enumerate(ids[:k], start=1):
            rel = 1.0 if doc_id in relevant else 0.0
            score += rel / math.log2(i + 1)
        return score

    ideal = dcg(sorted(ranked_ids[:k], key=lambda d: d in relevant, reverse=True))
    # Ideal should be perfect ordering of all relevants
    ideal_ids = list(relevant) + [d for d in ranked_ids if d not in relevant]
    ideal = dcg(ideal_ids)
    actual = dcg(ranked_ids)
    if ideal <= 0:
        return 0.0
    return actual / ideal
