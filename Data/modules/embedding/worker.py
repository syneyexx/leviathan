"""Specialist embedding batch worker handler."""

from __future__ import annotations

import hashlib
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


def _resolve_provider(ctx: dict[str, Any], model_id: str | None) -> Any:
    provider = ctx.get("embedding_provider")
    if provider is not None:
        return provider
    from Data.modules.knowledge.embeddings import build_embedding_provider

    kind = "auto"
    settings = ctx.get("settings")
    if settings is not None:
        emb = getattr(settings, "embeddings", None) or getattr(settings, "knowledge", None)
        if emb is not None:
            kind = str(getattr(emb, "provider", None) or getattr(emb, "embedding_kind", None) or "auto")
    return build_embedding_provider(kind=kind, model_name=model_id)


def process_embedding_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    texts = args.get("texts")
    if not isinstance(texts, list) or not texts:
        return _fail(store, job, "EMBEDDING_INPUT_INVALID: texts[] required", ctx=ctx)
    # Bound batch size — no 100k single call.
    safe_texts = [str(t) for t in texts[:512]]
    if len(texts) > 512:
        return _fail(
            store,
            job,
            "EMBEDDING_BATCH_TOO_LARGE: max 512 texts per job; split upstream",
            ctx=ctx,
        )

    cancel_check = ctx.get("job_cancel_check")
    if callable(cancel_check) and cancel_check():
        return _fail(store, job, "EMBEDDING_CANCELLED", ctx=ctx)

    model_id = str(args.get("model_id") or "") or None
    try:
        provider = _resolve_provider(ctx, model_id)
    except Exception as exc:  # noqa: BLE001
        return _fail(store, job, f"EMBEDDING_PROVIDER_UNAVAILABLE: {exc}", ctx=ctx)

    if not getattr(provider, "available", lambda: False)():
        status = provider.status() if hasattr(provider, "status") else {}
        return _fail(
            store,
            job,
            f"EMBEDDING_BACKEND_UNAVAILABLE: {status.get('reason') or status.get('error') or 'unavailable'}",
            ctx=ctx,
        )

    try:
        vectors = provider.embed_documents(safe_texts)
    except Exception as exc:  # noqa: BLE001
        return _fail(store, job, f"EMBEDDING_FAILED: {type(exc).__name__}: {exc}"[:500], ctx=ctx)

    # Cache identity metadata (content hash + provider + dims) — no vectors in JobStore when large.
    dims = len(vectors[0]) if vectors and vectors[0] else 0
    identities = [
        hashlib.sha256(
            f"{getattr(provider, 'provider_id', 'unknown')}|{model_id or ''}|{dims}|{t}".encode()
        ).hexdigest()[:16]
        for t in safe_texts
    ]
    result: dict[str, Any] = {
        "items_completed": len(safe_texts),
        "batches_completed": 1,
        "dimensions": dims,
        "provider_id": getattr(provider, "provider_id", None),
        "model_id": model_id,
        "identities": identities,
        "status": provider.status() if hasattr(provider, "status") else {},
        "truth": {
            "executed_via": "embedding_worker",
            "no_fastapi_inference": True,
            "is_semantic": bool(getattr(provider, "is_semantic", False)),
        },
    }
    # Keep vectors in result only for small batches; spill otherwise.
    if len(safe_texts) <= 32 and dims and dims * len(safe_texts) <= 32_768:
        result["vectors"] = vectors
    else:
        artifact_store = ctx.get("artifact_store")
        if artifact_store is not None and hasattr(artifact_store, "create_from_bytes"):
            import json

            body = json.dumps({"vectors": vectors, "identities": identities}).encode("utf-8")
            art = artifact_store.create_from_bytes(
                body,
                media_type="application/json",
                filename="embedding-batch.json",
                metadata={"kind": "embedding_batch", "items": len(safe_texts), "dimensions": dims},
            )
            result["artifact"] = (
                art.public_dict() if hasattr(art, "public_dict") else {"artifact_id": getattr(art, "artifact_id", None)}
            )
        else:
            result["vectors"] = vectors  # last resort for tests without ArtifactStore
    return _complete(store, job, result, ctx=ctx)
