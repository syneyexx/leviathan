"""Run retrieval benchmarks across lexical / semantic / hybrid weight grids.

Semantic path uses the same lexical scorer as a stand-in when embeddings are
unavailable — recorded honestly as lexical_proxy, not as true semantic quality.
"""

from __future__ import annotations

import time
from typing import Any

from evals.functional.retrieval_corpus import (
    DOCUMENTS,
    QUERIES,
    RETRIEVAL_CORPUS_VERSION,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from evals.functional.schema import ModelIdentity, finalize_outcome, new_record
from evals.functional.taxonomy import classify_campaign_failure
from evals.harness import git_start_commit
from reasoning.retrieval import expand_query_multilingual, lexical_score, merge_rank, rerank_hits
from reasoning.retrieval import RetrievalHit


def _hits_from_docs(query: str, *, multilingual_expand: bool = False) -> list[RetrievalHit]:
    q = expand_query_multilingual(query) if multilingual_expand else query
    hits: list[RetrievalHit] = []
    for doc in DOCUMENTS:
        score, reasons = lexical_score(q, doc["text"])
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                hit_id=doc["id"],
                kind=doc["store"],
                content=doc["text"],
                provenance=f"{doc['store']}:{doc['id']}",
                score=score,
                reasons=list(reasons) + (["ml_expand"] if multilingual_expand else []),
                metadata={"lang": doc["lang"], "stale": doc["stale"], "store": doc["store"]},
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


def _rank(
    query: str,
    *,
    mode: str,
    lexical_weight: float = 0.55,
    semantic_weight: float = 0.45,
    use_rerank: bool = False,
    multilingual_expand: bool = False,
    k: int = 5,
) -> tuple[list[str], dict[str, Any]]:
    lexical = _hits_from_docs(query, multilingual_expand=multilingual_expand)
    # Without embeddings, "semantic" is an honest lexical proxy for infrastructure
    # wiring tests — Layer B only. True semantic requires model/embeddings (Layer C).
    semantic_proxy = list(lexical)
    notes = ["synthetic_corpus", "semantic_is_lexical_proxy_without_embeddings"]
    if multilingual_expand:
        notes.append("multilingual_query_expand")

    if mode == "lexical":
        ranked = lexical[: max(k * 3, k)]
        method = "lexical" + ("+ml_expand" if multilingual_expand else "")
    elif mode == "semantic":
        ranked = semantic_proxy[: max(k * 3, k)]
        method = "semantic_proxy"
    else:
        merged = merge_rank(
            lexical,
            semantic_proxy,
            lexical_weight=lexical_weight,
            semantic_weight=semantic_weight,
            limit=k,
        )
        ranked = list(merged.hits)
        method = f"hybrid_l{lexical_weight}_s{semantic_weight}"
        notes.extend(merged.notes)

    if use_rerank:
        ranked = rerank_hits(query, ranked, limit=max(k * 2, 8))
        method = f"{method}+rerank"

    ids = [h.hit_id for h in ranked[:k]]
    return ids, {"method": method, "notes": notes, "hit_count": len(ranked)}


def run_retrieval_suite(
    *,
    modes: list[str] | None = None,
    k: int = 5,
    weight_grid: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    started = time.time()
    sha = git_start_commit()
    modes = modes or ["lexical", "lexical+ml_expand", "semantic", "hybrid", "hybrid+rerank"]
    weight_grid = weight_grid or [(0.55, 0.45), (0.7, 0.3), (0.4, 0.6), (1.0, 0.0), (0.0, 1.0)]

    summaries: dict[str, Any] = {}
    all_records: list[dict[str, Any]] = []

    for mode in modes:
        weights = weight_grid if mode.startswith("hybrid") else [(0.55, 0.45)]
        for lw, sw in weights:
            key = mode if not mode.startswith("hybrid") else f"{mode}|l{lw}|s{sw}"
            metrics_acc = {"recall": [], "precision": [], "mrr": [], "ndcg": [], "stale_hit": [], "wrong_store": []}
            for q in QUERIES:
                t0 = time.perf_counter()
                use_rerank = "rerank" in mode
                ml_expand = "ml_expand" in mode
                base_mode = "hybrid" if mode.startswith("hybrid") else ("lexical" if "lexical" in mode else mode)
                if mode == "semantic":
                    base_mode = "semantic"
                ranked_ids, meta = _rank(
                    q["text"],
                    mode=base_mode,
                    lexical_weight=lw,
                    semantic_weight=sw,
                    use_rerank=use_rerank,
                    multilingual_expand=ml_expand,
                    k=k,
                )
                relevant = set(q.get("relevant") or [])
                rec_at = recall_at_k(relevant, ranked_ids, k)
                prec = precision_at_k(relevant, ranked_ids, k)
                rr = mrr(relevant, ranked_ids)
                nd = ndcg_at_k(relevant, ranked_ids, k)
                stale_ids = set(q.get("stale_ids") or [])
                stale_hit = 1.0 if any(i in stale_ids for i in ranked_ids[:k]) else 0.0
                wrong_store = 0.0
                if q.get("wrong_store_if"):
                    # wrong if top hit store is in forbidden list and relevant missed
                    top = next((d for d in DOCUMENTS if d["id"] == (ranked_ids[0] if ranked_ids else "")), None)
                    if top and top["store"] in q["wrong_store_if"] and not (set(ranked_ids[:1]) & relevant):
                        wrong_store = 1.0

                metrics_acc["recall"].append(rec_at)
                metrics_acc["precision"].append(prec)
                metrics_acc["mrr"].append(rr)
                metrics_acc["ndcg"].append(nd)
                metrics_acc["stale_hit"].append(stale_hit)
                metrics_acc["wrong_store"].append(wrong_store)

                passed = rec_at > 0 or not relevant
                outcome = "success" if passed else "failure"
                tax = classify_campaign_failure(
                    outcome=outcome,
                    family="retrieval",
                    signals={"retrieval_miss": not passed},
                )
                rec = new_record(
                    task_id=f"{q['id']}::{key}",
                    task_family="retrieval",
                    git_sha=sha,
                    eval_layer="B_deterministic",
                    task_split=q.get("split") or "dev",
                    synthetic=True,
                    model=ModelIdentity(model_runtime="deterministic_lexical"),
                    input={"query": q["text"], "mode": key},
                    ground_truth={"relevant": list(relevant)},
                    result={"ranked": ranked_ids, **meta},
                    verified_result={
                        "recall@k": rec_at,
                        "precision@k": prec,
                        "mrr": rr,
                        "ndcg@k": nd,
                    },
                    outcome=outcome,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                    retrieval_stats={"k": k, "mode": key},
                    failure_class=tax["failure_class"] if outcome != "success" else "passed",
                )
                finalize_outcome(rec)
                all_records.append(rec.to_dict())

            def _avg(xs: list[float]) -> float:
                return round(sum(xs) / len(xs), 4) if xs else 0.0

            summaries[key] = {
                "Recall@K": _avg(metrics_acc["recall"]),
                "Precision@K": _avg(metrics_acc["precision"]),
                "MRR": _avg(metrics_acc["mrr"]),
                "nDCG@K": _avg(metrics_acc["ndcg"]),
                "stale_hit_rate": _avg(metrics_acc["stale_hit"]),
                "wrong_store_rate": _avg(metrics_acc["wrong_store"]),
                "sample_size": len(QUERIES),
                "k": k,
            }

    # Prefer hybrid config with best Recall@K among hybrid keys (measurement, not claim).
    hybrid_keys = [k for k in summaries if k.startswith("hybrid")]
    best = None
    if hybrid_keys:
        best = max(hybrid_keys, key=lambda kk: summaries[kk]["Recall@K"])

    return {
        "suite": "retrieval",
        "corpus_version": RETRIEVAL_CORPUS_VERSION,
        "git_sha": sha,
        "duration_seconds": round(time.time() - started, 3),
        "document_count": len(DOCUMENTS),
        "query_count": len(QUERIES),
        "summaries": summaries,
        "recommended_hybrid_from_fixture": best,
        "recommended_metrics": summaries.get(best) if best else None,
        "honesty": [
            "Semantic mode without embeddings is a lexical proxy (Layer B).",
            "Do not treat fixture-tuned weights as production defaults without Layer C.",
            "Current production defaults remain 0.55/0.45 until host semantic benchmark justifies change.",
        ],
        "records": all_records,
        "status": "PASS",
    }
