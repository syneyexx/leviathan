"""Specialist rerank batch worker handler — honest unavailable when backend missing."""

from __future__ import annotations

from typing import Any


def _fail(store: Any, job: Any, error: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            ctx=ctx,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"error": error}


def _complete(store: Any, job: Any, result: dict[str, Any], *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    fenced_transition(
        store,
        job.job_id,
        JobState.COMPLETED,
        worker_id=worker_id,
        ctx=ctx,
        result=result,
    )
    return result


def process_rerank_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    query = str(args.get("query") or "").strip()
    documents = args.get("documents")
    if not query or not isinstance(documents, list) or not documents:
        return _fail(store, job, "RERANK_INPUT_INVALID: query and documents[] required", ctx=ctx)
    docs = [str(d) for d in documents[:256]]
    top_k = max(1, min(int(args.get("top_k") or len(docs)), len(docs)))

    cancel_check = ctx.get("job_cancel_check")
    if callable(cancel_check) and cancel_check():
        return _fail(store, job, "RERANK_CANCELLED", ctx=ctx)

    provider = ctx.get("rerank_provider")
    if provider is None:
        from Data.modules.knowledge.embeddings import RerankerProvider

        model_id = str(args.get("model_id") or "") or None
        settings = ctx.get("settings")
        if model_id is None and settings is not None:
            model_id = getattr(getattr(settings, "embeddings", None), "reranker_model", None)
        provider = RerankerProvider(model_name=model_id)

    if not getattr(provider, "available", lambda: False)():
        status = provider.status() if hasattr(provider, "status") else {}
        # Honest unavailable — do NOT label lexical fallback as neural reranking.
        return _complete(
            store,
            job,
            {
                "status": "UNAVAILABLE",
                "reranker": "unavailable",
                "reason": status.get("error") or "reranker_not_configured",
                "fallback": "lexical_order_preserved",
                "ranked": [
                    {"index": i, "score": None, "document": d[:200]}
                    for i, d in enumerate(docs[:top_k])
                ],
                "truth": {
                    "neural_rerank": False,
                    "fallback_is_not_neural_reranking": True,
                    "executed_via": "rerank_worker",
                },
            },
            ctx=ctx,
        )

    try:
        scores = provider.score(query, docs)
    except Exception as exc:  # noqa: BLE001
        return _fail(store, job, f"RERANK_FAILED: {type(exc).__name__}: {exc}"[:500], ctx=ctx)

    ranked = sorted(
        (
            {"index": i, "score": float(scores[i]), "document": docs[i][:200]}
            for i in range(len(docs))
        ),
        key=lambda r: (-r["score"], r["index"]),
    )[:top_k]
    return _complete(
        store,
        job,
        {
            "status": "OK",
            "reranker": "configured",
            "provider_id": getattr(provider, "provider_id", "cross_encoder"),
            "model_id": args.get("model_id"),
            "candidates_completed": len(docs),
            "ranked": ranked,
            "truth": {
                "neural_rerank": True,
                "executed_via": "rerank_worker",
                "no_fastapi_inference": True,
            },
        },
        ctx=ctx,
    )
