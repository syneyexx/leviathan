"""Embedding pool — specialist batch vector inference (no Knowledge SQLite bulk writes)."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool
from Data.modules.workers.loop import _default_gateway_execute


def _provider(ctx: dict[str, Any]) -> Any:
    from Data.modules.knowledge import build_embedding_provider

    settings = ctx["settings"]
    kind = getattr(settings.knowledge, "embedding_provider", "auto")
    model_name = getattr(settings.knowledge, "embedding_model", None)
    return build_embedding_provider(kind=kind, model_name=model_name)


def _knowledge_db(ctx: dict[str, Any]) -> Any:
    from Data.modules.common.database_domains import knowledge_path_from_settings

    return knowledge_path_from_settings(ctx["settings"])


def _complete(ctx: dict[str, Any], job: Any, result: dict[str, Any]) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    fenced_transition(
        ctx["job_store"],
        job.job_id,
        JobState.COMPLETED,
        result=result,
        worker_id=str(ctx.get("worker_id") or ""),
        ctx=ctx,
    )
    return result


def _fail(ctx: dict[str, Any], job: Any, error: str) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    fenced_transition(
        ctx["job_store"],
        job.job_id,
        JobState.FAILED,
        error=error[:500],
        worker_id=str(ctx.get("worker_id") or ""),
        ctx=ctx,
    )
    return {"error": error}


def _job_cancelled(ctx: dict[str, Any], job: Any) -> bool:
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


def _handle_batch(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    args = dict(getattr(job, "arguments", None) or {})
    document_id = str(args.get("document_id") or "").strip()
    texts = list(args.get("texts") or [])
    chunk_ids = list(args.get("chunk_ids") or [])
    content_hashes = list(args.get("content_hashes") or [])
    expected_hash = str(args.get("expected_content_hash") or "")
    finalize = bool(args.get("finalize", False))
    provider_hint = str(args.get("provider_id") or "")

    if _job_cancelled(ctx, job):
        return _fail(ctx, job, "CANCELLED")

    if not texts:
        return _fail(ctx, job, "EMBEDDING_FAILED: empty batch")

    provider = _provider(ctx)
    if provider is None or not provider.available():
        # Honest unavailable — do not fabricate vectors; leave document lexical if chunks exist.
        return _complete(
            ctx,
            job,
            {
                "status": "EMBEDDING_UNAVAILABLE",
                "document_id": document_id,
                "embedded": 0,
                "provider_id": getattr(provider, "provider_id", provider_hint) if provider else provider_hint,
                "truth": {"no_fake_zero_vectors": True, "backend_ready": False},
            },
        )

    try:
        vectors = provider.embed_documents([str(t) for t in texts])
    except Exception as exc:  # noqa: BLE001
        return _fail(ctx, job, f"EMBEDDING_FAILED: {exc}")

    if len(vectors) != len(texts):
        return _fail(ctx, job, "EMBEDDING_FAILED: vector count mismatch")

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

    if not document_id:
        # Pure inference result — no Knowledge commit (caller may use vectors).
        return _complete(
            ctx,
            job,
            {
                "status": "OK",
                "embedded": len(embeddings),
                "provider_id": provider.provider_id,
                "dimensions": len(vectors[0]) if vectors else 0,
                "vectors_omitted": True,
                "executed_via": "embedding_worker",
            },
        )

    from Data.modules.knowledge.commit_submit import submit_knowledge_chunk_embeddings

    db_path = _knowledge_db(ctx)
    submit = submit_knowledge_chunk_embeddings(
        db_path,
        document_id=document_id,
        expected_content_hash=expected_hash,
        embeddings=embeddings,
        provider_id=provider.provider_id,
        finalize=finalize,
        source_job_id=str(job.job_id),
        idempotency_key=(
            f"knowledge:embeddings:{document_id}:{expected_hash}:"
            f"{provider.provider_id}:{args.get('batch_index', 0)}"
        ),
    )
    receipt = submit.receipt
    if receipt is not None and str(getattr(receipt, "status", "")) == "REJECTED":
        code = getattr(receipt, "error_code", "") or "KNOWLEDGE_COMMIT_FAILED"
        return _fail(ctx, job, f"{code}: {getattr(receipt, 'error_message', '')}")

    return _complete(
        ctx,
        job,
        {
            "status": "OK",
            "document_id": document_id,
            "embedded": len(embeddings),
            "provider_id": provider.provider_id,
            "dimensions": len(vectors[0]) if vectors else 0,
            "finalize": finalize,
            "commit_id": submit.commit_id,
            "ack_status": submit.ack_status,
            "executed_via": "embedding_worker",
            "truth": {
                "inference_owner": "embedding",
                "commit_owner": "db_commit",
                "no_direct_knowledge_sqlite_bulk_write": True,
            },
        },
    )


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    cap = str(getattr(job, "capability_id", "") or "")
    if cap.startswith("embedding."):
        return _handle_batch(ctx, job)
    lease_ttl = float(
        ctx.get("lease_ttl_seconds")
        or getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0)
        or 30.0
    )
    return _default_gateway_execute(
        ctx["job_runtime"],
        ctx["job_store"],
        job,
        str(ctx.get("worker_id") or "embedding"),
        lease_ttl,
    )


def main(argv=None):
    return main_for_pool("embedding", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
