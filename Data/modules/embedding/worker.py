"""Specialist embedding batch worker handler.

Owns vector inference only. When Knowledge chunk IDs are present, submits typed
``knowledge.upsert_chunk_embeddings`` CommitIntents — never bulk-writes Knowledge
SQLite tables directly.
"""

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


def _job_cancelled(ctx: dict[str, Any], job: Any) -> bool:
    cancel_check = ctx.get("job_cancel_check")
    if callable(cancel_check) and cancel_check():
        return True
    store = ctx.get("job_store")
    if store is None:
        return False
    try:
        current = store.get(job.job_id)
    except Exception:  # noqa: BLE001
        return False
    if current is None:
        return False
    state = getattr(current, "state", None)
    value = getattr(state, "value", None) or str(state or "")
    return value.upper() in {"CANCEL_REQUESTED", "CANCELLED", "CANCELED"}


def _resolve_provider(ctx: dict[str, Any], model_id: str | None) -> Any:
    provider = ctx.get("embedding_provider")
    if provider is not None:
        return provider
    from Data.modules.knowledge.embeddings import build_embedding_provider

    kind = "auto"
    settings = ctx.get("settings")
    if settings is not None:
        knowledge = getattr(settings, "knowledge", None)
        if knowledge is not None:
            kind = str(
                getattr(knowledge, "embedding_provider", None)
                or getattr(knowledge, "embedding_kind", None)
                or getattr(knowledge, "provider", None)
                or "auto"
            )
            if model_id is None:
                model_id = getattr(knowledge, "embedding_model", None)
        else:
            emb = getattr(settings, "embeddings", None)
            if emb is not None:
                kind = str(
                    getattr(emb, "provider", None)
                    or getattr(emb, "embedding_kind", None)
                    or "auto"
                )
    return build_embedding_provider(kind=kind, model_name=model_id)


def _knowledge_db(ctx: dict[str, Any]) -> Any:
    from Data.modules.common.database_domains import knowledge_path_from_settings

    settings = ctx.get("settings")
    if settings is None:
        raise RuntimeError("settings required for Knowledge embedding commit")
    return knowledge_path_from_settings(settings)


def _commit_knowledge_embeddings(
    ctx: dict[str, Any],
    job: Any,
    *,
    document_id: str,
    expected_hash: str,
    embeddings: list[dict[str, Any]],
    provider_id: str,
    finalize: bool,
    batch_index: int,
) -> dict[str, Any]:
    from Data.modules.knowledge.commit_submit import submit_knowledge_chunk_embeddings

    db_path = _knowledge_db(ctx)
    submit = submit_knowledge_chunk_embeddings(
        db_path,
        document_id=document_id,
        expected_content_hash=expected_hash,
        embeddings=embeddings,
        provider_id=provider_id,
        finalize=finalize,
        source_job_id=str(job.job_id),
        idempotency_key=(
            f"knowledge:embeddings:{document_id}:{expected_hash}:"
            f"{provider_id}:{batch_index}"
        ),
    )
    receipt = submit.receipt
    if receipt is not None and str(getattr(receipt, "status", "")) == "REJECTED":
        code = getattr(receipt, "error_code", "") or "KNOWLEDGE_COMMIT_FAILED"
        return {
            "ok": False,
            "error": f"{code}: {getattr(receipt, 'error_message', '')}",
        }
    return {
        "ok": True,
        "commit_id": submit.commit_id,
        "ack_status": submit.ack_status,
        "committed": bool(submit.committed or receipt is not None),
    }


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

    if _job_cancelled(ctx, job):
        return _fail(store, job, "EMBEDDING_CANCELLED", ctx=ctx)

    document_id = str(args.get("document_id") or "").strip()
    chunk_ids = list(args.get("chunk_ids") or [])
    content_hashes = list(args.get("content_hashes") or [])
    expected_hash = str(args.get("expected_content_hash") or "")
    finalize = bool(args.get("finalize", False))
    provider_hint = str(args.get("provider_id") or "")
    batch_index = int(args.get("batch_index") or 0)

    model_id = str(args.get("model_id") or "") or None
    try:
        provider = _resolve_provider(ctx, model_id)
    except Exception as exc:  # noqa: BLE001
        if document_id:
            # Knowledge path: honest unavailable (lexical index may already be READY).
            return _complete(
                store,
                job,
                {
                    "status": "EMBEDDING_UNAVAILABLE",
                    "document_id": document_id,
                    "embedded": 0,
                    "provider_id": provider_hint,
                    "truth": {"no_fake_zero_vectors": True, "backend_ready": False},
                },
                ctx=ctx,
            )
        return _fail(store, job, f"EMBEDDING_PROVIDER_UNAVAILABLE: {exc}", ctx=ctx)

    if not getattr(provider, "available", lambda: False)():
        status = provider.status() if hasattr(provider, "status") else {}
        if document_id:
            return _complete(
                store,
                job,
                {
                    "status": "EMBEDDING_UNAVAILABLE",
                    "document_id": document_id,
                    "embedded": 0,
                    "provider_id": getattr(provider, "provider_id", provider_hint),
                    "truth": {
                        "no_fake_zero_vectors": True,
                        "backend_ready": False,
                        "reason": status.get("reason") or status.get("error") or "unavailable",
                    },
                },
                ctx=ctx,
            )
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

    if len(vectors) != len(safe_texts):
        return _fail(store, job, "EMBEDDING_FAILED: vector count mismatch", ctx=ctx)

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
        "status": "OK",
        "provider_status": provider.status() if hasattr(provider, "status") else {},
        "truth": {
            "executed_via": "embedding_worker",
            "no_fastapi_inference": True,
            "is_semantic": bool(getattr(provider, "is_semantic", False)),
        },
    }

    # Knowledge commit path — typed intent, no direct bulk SQLite writes.
    if document_id:
        embeddings: list[dict[str, Any]] = []
        for i, vector in enumerate(vectors):
            chunk_id = str(chunk_ids[i]) if i < len(chunk_ids) else ""
            if not chunk_id:
                continue
            embeddings.append(
                {
                    "chunk_id": chunk_id,
                    "vector": [float(x) for x in vector],
                    "dimensions": len(vector),
                    "provider_id": provider.provider_id,
                    "content_hash": str(content_hashes[i]) if i < len(content_hashes) else "",
                }
            )
        commit_meta = _commit_knowledge_embeddings(
            ctx,
            job,
            document_id=document_id,
            expected_hash=expected_hash,
            embeddings=embeddings,
            provider_id=str(provider.provider_id),
            finalize=finalize,
            batch_index=batch_index,
        )
        if not commit_meta.get("ok"):
            return _fail(store, job, str(commit_meta.get("error") or "KNOWLEDGE_COMMIT_FAILED"), ctx=ctx)
        result.update(
            {
                "document_id": document_id,
                "embedded": len(embeddings),
                "finalize": finalize,
                "commit_id": commit_meta.get("commit_id"),
                "ack_status": commit_meta.get("ack_status"),
                "vectors_omitted": True,
                "truth": {
                    **result["truth"],
                    "inference_owner": "embedding",
                    "commit_owner": "db_commit",
                    "no_direct_knowledge_sqlite_bulk_write": True,
                },
            }
        )
        return _complete(store, job, result, ctx=ctx)

    # Generic embedding.batch — keep vectors in result only for small batches; spill otherwise.
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
