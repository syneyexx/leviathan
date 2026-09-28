"""Knowledge prepare pool — scan / normalize / chunk / embedding plan.

Never performs bulk canonical SQLite COMMIT_WRITE; that is db_commit.
Never runs embedding inference; that is the embedding worker.
"""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool
from Data.modules.workers.loop import _default_gateway_execute

DEFAULT_EMBED_BATCH = 64
MAX_EMBED_FANOUT = 32


def _knowledge_store(ctx: dict[str, Any]) -> Any:
    from Data.modules.common.database_domains import knowledge_path_from_settings
    from Data.modules.knowledge import KnowledgeStore, build_embedding_provider

    settings = ctx["settings"]
    db_path = knowledge_path_from_settings(settings)
    provider = None
    try:
        kind = getattr(settings.knowledge, "embedding_provider", "auto")
        model_name = getattr(settings.knowledge, "embedding_model", None)
        provider = build_embedding_provider(kind=kind, model_name=model_name)
    except Exception:  # noqa: BLE001
        provider = None
    store = KnowledgeStore(
        db_path,
        data_root=settings.knowledge.data_root,
        chunk_max_chars=settings.knowledge.chunk_max_chars,
        chunk_overlap=settings.knowledge.chunk_overlap,
        embedding_provider=provider,
    )
    store.initialize_schema()
    return store


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


def _progress(ctx: dict[str, Any], job: Any, *, phase: str, message: str = "", **extra: Any) -> None:
    store = ctx.get("job_store")
    if store is not None and hasattr(store, "update_progress"):
        try:
            store.update_progress(job.job_id, phase=phase, message=message, **extra)
        except TypeError:
            store.update_progress(job.job_id, phase=phase, message=message)
        except Exception:  # noqa: BLE001
            pass


def _enqueue_embedding_batches(
    ctx: dict[str, Any],
    job: Any,
    *,
    document_id: str,
    content_hash: str,
    prepared: Any,
) -> list[str]:
    from Data.modules.knowledge.preparation import (
        embedding_batch_idempotency_key,
        partition_embedding_batches,
    )

    runtime = ctx.get("job_runtime")
    if runtime is None:
        return []
    batches = partition_embedding_batches(prepared.chunks, batch_size=DEFAULT_EMBED_BATCH)
    if len(batches) > MAX_EMBED_FANOUT:
        # Bound fanout — remaining chunks wait for a follow-up prepare continuation.
        batches = batches[:MAX_EMBED_FANOUT]
    child_ids: list[str] = []
    root_id = getattr(job, "root_job_id", None) or job.job_id
    for index, batch in enumerate(batches):
        if _job_cancelled(ctx, job):
            break
        texts = [c.content for c in batch]
        chunk_ids = [c.chunk_id for c in batch]
        hashes = [c.content_hash for c in batch]
        child = runtime.enqueue(
            capability_id="embedding.batch",
            arguments={
                "document_id": document_id,
                "expected_content_hash": content_hash,
                "provider_id": prepared.embedding_provider_id,
                "chunk_ids": chunk_ids,
                "content_hashes": hashes,
                "texts": texts,
                "finalize": False,
                "batch_index": index,
                "batch_count": len(batches),
            },
            requested_by="knowledge_prepare",
            domain="knowledge",
            domain_entity_type="document",
            domain_entity_id=document_id,
            worker_pool="embedding",
            resource_class="GPU_SHARED",
            latency_class="background",
            parent_job_id=job.job_id,
            root_job_id=root_id,
            idempotency_key=embedding_batch_idempotency_key(
                document_id=document_id,
                content_hash=content_hash,
                provider_id=prepared.embedding_provider_id or "default",
                batch_index=index,
            ),
            metadata={
                "document_id": document_id,
                "phase": "embedding",
                "batch_index": index,
            },
        )
        child_ids.append(child.job_id)
    return child_ids


def _commit_prepared_index(
    ctx: dict[str, Any],
    job: Any,
    *,
    store: Any,
    prepared: Any,
    document_content: str,
    finalize: bool,
) -> dict[str, Any]:
    from Data.modules.knowledge.commit_submit import submit_knowledge_replace_chunks

    result = submit_knowledge_replace_chunks(
        store.path,
        document_id=prepared.document_id,
        expected_content_hash=prepared.expected_content_hash,
        title=prepared.title,
        chunks=[c.public_dict() for c in prepared.chunks],
        source=prepared.source,
        finalize=finalize,
        document_content_for_fts=document_content,
        source_job_id=str(job.job_id),
        idempotency_key=(
            f"knowledge:replace_chunks:{prepared.document_id}:"
            f"{prepared.expected_content_hash}:{prepared.chunk_max_chars}:"
            f"{prepared.chunk_overlap}:{int(finalize)}"
        ),
    )
    receipt = result.receipt
    status = getattr(receipt, "status", None) if receipt else None
    if receipt is not None and str(status) == "REJECTED":
        return {
            "accepted": False,
            "commit_id": result.commit_id,
            "error_code": getattr(receipt, "error_code", "") or "KNOWLEDGE_COMMIT_FAILED",
            "error": getattr(receipt, "error_message", "") or result.message,
        }
    return {
        "accepted": result.accepted,
        "committed": bool(result.committed or (receipt is not None and str(status) == "APPLIED")),
        "commit_id": result.commit_id,
        "ack_status": result.ack_status,
        "message": result.message,
    }


def _prepare_document(ctx: dict[str, Any], job: Any, document_id: str) -> dict[str, Any]:
    from Data.modules.knowledge.types import IngestStatus

    if _job_cancelled(ctx, job):
        return _fail(ctx, job, "CANCELLED")

    store = _knowledge_store(ctx)
    doc = store.get_document(document_id)
    if doc is None:
        return _fail(ctx, job, f"KNOWLEDGE_STALE_GENERATION: document missing {document_id}")

    _progress(ctx, job, phase="normalizing", message="normalize + chunk plan")
    prepared = store.build_prepared_index(document_id)
    if _job_cancelled(ctx, job):
        return _fail(ctx, job, "CANCELLED")

    _progress(
        ctx,
        job,
        phase="chunking",
        message=f"chunks={len(prepared.chunks)}",
    )
    needs_embed = bool(prepared.needs_embeddings and prepared.chunks)
    commit_meta = _commit_prepared_index(
        ctx,
        job,
        store=store,
        prepared=prepared,
        document_content=doc.content or "",
        # Lexical index becomes READY immediately; vectors catch up asynchronously.
        # Health reports embedding coverage separately — never fake vector completeness.
        finalize=True,
    )
    if not commit_meta.get("accepted"):
        try:
            store.finalize_document(
                document_id,
                expected_content_hash=prepared.expected_content_hash,
                status=IngestStatus.FAILED,
                error=str(commit_meta.get("error") or "KNOWLEDGE_COMMIT_FAILED")[:500],
            )
        except Exception:  # noqa: BLE001
            pass
        return _fail(
            ctx,
            job,
            f"{commit_meta.get('error_code') or 'KNOWLEDGE_COMMIT_FAILED'}: "
            f"{commit_meta.get('error') or 'commit rejected'}",
        )

    embedding_jobs: list[str] = []
    if needs_embed:
        _progress(ctx, job, phase="embedding_pending", message="enqueue embedding batches")
        embedding_jobs = _enqueue_embedding_batches(
            ctx,
            job,
            document_id=document_id,
            content_hash=prepared.expected_content_hash,
            prepared=prepared,
        )

    refreshed = store.get_document(document_id)
    result = {
        "action": "prepare",
        "document_id": document_id,
        "document": refreshed.public_dict() if refreshed else None,
        "status": getattr(getattr(refreshed, "status", None), "value", None)
        or str(getattr(refreshed, "status", "")),
        "chunk_count": len(prepared.chunks),
        "normalization_version": prepared.normalization_version,
        "needs_embeddings": needs_embed,
        "embedding_jobs": embedding_jobs,
        "embedding_provider_id": prepared.embedding_provider_id,
        "embedding_unavailable_reason": prepared.embedding_unavailable_reason,
        "commit": commit_meta,
        "executed_via": "knowledge_prepare_worker",
        "truth": {
            "no_inline_embedding_inference": True,
            "bulk_commit_via_db_commit": True,
        },
    }
    return _complete(ctx, job, result)


def _prepare_document_body(ctx: dict[str, Any], job: Any, document_id: str) -> dict[str, Any]:
    """Prepare + commit without fencing job completion (for scan fan-in)."""
    store = _knowledge_store(ctx)
    doc = store.get_document(document_id)
    if doc is None:
        return {"error": f"missing:{document_id}", "document_id": document_id}
    prepared = store.build_prepared_index(document_id)
    needs_embed = bool(prepared.needs_embeddings and prepared.chunks)
    commit_meta = _commit_prepared_index(
        ctx,
        job,
        store=store,
        prepared=prepared,
        document_content=doc.content or "",
        finalize=True,
    )
    embedding_jobs: list[str] = []
    if needs_embed and commit_meta.get("accepted"):
        embedding_jobs = _enqueue_embedding_batches(
            ctx,
            job,
            document_id=document_id,
            content_hash=prepared.expected_content_hash,
            prepared=prepared,
        )
    return {
        "document_id": document_id,
        "chunk_count": len(prepared.chunks),
        "needs_embeddings": needs_embed,
        "embedding_jobs": embedding_jobs,
        "commit": commit_meta,
    }


def _handle_ingest_scan_v2(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    args = dict(getattr(job, "arguments", None) or {})
    limit = min(max(int(args.get("limit") or 50), 1), 5000)
    store = _knowledge_store(ctx)
    root = store.data_root
    if root is None or not root.exists() or not root.is_dir():
        return _complete(
            ctx,
            job,
            {
                "scanned": 0,
                "ingested": 0,
                "unchanged": 0,
                "data_root": str(root) if root else None,
                "document_ids": [],
                "executed_via": "knowledge_prepare_worker",
            },
        )

    from Data.modules.knowledge.store import TEXT_SUFFIXES

    discovered = 0
    unchanged = 0
    changed_or_new = 0
    document_ids: list[str] = []
    errors: list[dict[str, str]] = []

    for path in sorted(root.rglob("*")):
        if discovered >= limit:
            break
        if _job_cancelled(ctx, job):
            return _fail(ctx, job, "CANCELLED")
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        discovered += 1
        try:
            classification = store.classify_ingest_path(path)
        except Exception as exc:  # noqa: BLE001
            errors.append({"path": str(path), "error": str(exc)[:200]})
            continue
        kind = classification.get("classification")
        if kind == "UNCHANGED":
            unchanged += 1
            if classification.get("document_id"):
                document_ids.append(str(classification["document_id"]))
            continue
        if kind in {"SKIPPED_TOO_LARGE", "UNSUPPORTED", "MISSING"}:
            continue
        changed_or_new += 1
        try:
            # Stage content + ingest index without fused embedding.
            data = path.read_bytes()
            text = data.decode("utf-8", errors="replace")
            from Data.modules.knowledge.hashing import file_sha256
            from datetime import datetime, timezone

            digest = file_sha256(data)
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(
                timespec="seconds"
            )
            document_id = classification.get("document_id") or None
            title = path.stem.replace("_", " ").strip() or path.name
            staged = store.stage_document(
                document_id=document_id,
                title=title,
                content=text,
                source="modeldata",
                original_path=str(path),
                source_mtime=mtime,
                size_bytes=stat.st_size,
                trust_metadata={"trust": "local_file", "root": str(store.data_root)},
            )
            # Update ingest file index (bounded CONTROL_WRITE bookkeeping).
            with store.connect() as conn:
                store._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO knowledge_ingest_files(
                        path, size_bytes, mtime, content_hash, document_id, status,
                        parser_version, ingest_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(path) DO UPDATE SET
                        size_bytes = excluded.size_bytes,
                        mtime = excluded.mtime,
                        content_hash = excluded.content_hash,
                        document_id = excluded.document_id,
                        status = excluded.status,
                        parser_version = excluded.parser_version,
                        ingest_version = excluded.ingest_version,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(path),
                        stat.st_size,
                        mtime,
                        digest,
                        staged.document_id,
                        "INDEXING",
                        "1.0.0",
                        3,
                    ),
                )
            prep = _prepare_document_body(ctx, job, staged.document_id)
            if prep.get("document_id"):
                document_ids.append(str(prep["document_id"]))
                with store.connect() as conn:
                    conn.execute(
                        "UPDATE knowledge_ingest_files SET status = ?, updated_at = datetime('now') WHERE path = ?",
                        ("READY", str(path)),
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append({"path": str(path), "error": str(exc)[:200]})

        _progress(
            ctx,
            job,
            phase="scanning",
            message=f"discovered={discovered} changed={changed_or_new} unchanged={unchanged}",
        )

    return _complete(
        ctx,
        job,
        {
            "scanned": discovered,
            "ingested": changed_or_new,
            "unchanged": unchanged,
            "errors": errors,
            "data_root": str(root),
            "document_ids": document_ids,
            "executed_via": "knowledge_prepare_worker",
            "truth": {
                "incremental_scan": True,
                "uses_knowledge_v2_ingest": True,
                "no_parallel_ingest_pipeline": True,
            },
        },
    )


def _handle_prepare(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    args = dict(getattr(job, "arguments", None) or {})
    action = str(args.get("action") or "prepare").strip().lower()
    store = _knowledge_store(ctx)
    try:
        if action in {"backfill", "content_backfill"}:
            # Backfill: prepare plans + commit via db_commit path (batched).
            limit = min(max(int(args.get("limit") or 50), 1), 500)
            pending_ids: list[str] = []
            with store.connect() as conn:
                store._ensure_schema(conn)
                rows = conn.execute(
                    """
                    SELECT d.id FROM knowledge_documents d
                    WHERE COALESCE(d.status, 'READY') = 'READY'
                      AND LENGTH(TRIM(COALESCE(d.content, ''))) > 0
                      AND NOT EXISTS (
                        SELECT 1 FROM knowledge_chunks c WHERE c.document_id = d.id
                      )
                    ORDER BY d.updated_at ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                pending_ids = [r["id"] for r in rows]
            processed: list[str] = []
            errors: list[dict[str, str]] = []
            for doc_id in pending_ids:
                if _job_cancelled(ctx, job):
                    return _fail(ctx, job, "CANCELLED")
                try:
                    # Force INDEXING then prepare.
                    doc = store.get_document(doc_id)
                    if doc is None:
                        continue
                    store.stage_document(
                        document_id=doc.document_id,
                        title=doc.title,
                        content=doc.content,
                        source=doc.source,
                        original_path=doc.original_path,
                        source_mtime=doc.source_mtime,
                        size_bytes=doc.size_bytes,
                    )
                    body = _prepare_document_body(ctx, job, doc_id)
                    if body.get("error"):
                        errors.append({"document_id": doc_id, "error": str(body["error"])[:300]})
                    else:
                        processed.append(doc_id)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"document_id": doc_id, "error": str(exc)[:300]})
            remaining = store.count_pending_content_backfill()
            return _complete(
                ctx,
                job,
                {
                    "action": action,
                    "processed": len(processed),
                    "document_ids": processed,
                    "errors": errors,
                    "remaining": remaining,
                    "status": "KNOWLEDGE_BACKFILL_PENDING" if remaining else "KNOWLEDGE_BACKFILL_DONE",
                    "executed_via": "knowledge_prepare_worker",
                },
            )

        if action in {"ingest_path", "path"}:
            path = str(args.get("path") or "").strip()
            if not path:
                raise ValueError("path is required for ingest_path")
            resolved = store.resolve_under_data_root(path)
            classification = store.classify_ingest_path(resolved)
            if classification.get("classification") == "UNCHANGED":
                record = store.get_document(str(classification["document_id"]))
                return _complete(
                    ctx,
                    job,
                    {
                        "action": action,
                        "ingested": False,
                        "reason": "unchanged",
                        "document": record.public_dict() if record else None,
                        "executed_via": "knowledge_prepare_worker",
                    },
                )
            data = resolved.read_bytes()
            text = data.decode("utf-8", errors="replace")
            from Data.modules.knowledge.hashing import file_sha256
            from datetime import datetime, timezone

            digest = file_sha256(data)
            stat = resolved.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(
                timespec="seconds"
            )
            document_id = classification.get("document_id")
            title = resolved.stem.replace("_", " ").strip() or resolved.name
            staged = store.stage_document(
                document_id=document_id,
                title=title,
                content=text,
                source=str(args.get("source") or "modeldata"),
                original_path=str(resolved),
                source_mtime=mtime,
                size_bytes=stat.st_size,
                trust_metadata={"trust": "local_file", "root": str(store.data_root)},
            )
            with store.connect() as conn:
                store._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO knowledge_ingest_files(
                        path, size_bytes, mtime, content_hash, document_id, status,
                        parser_version, ingest_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'INDEXING', '1.0.0', 3, datetime('now'))
                    ON CONFLICT(path) DO UPDATE SET
                        size_bytes = excluded.size_bytes,
                        mtime = excluded.mtime,
                        content_hash = excluded.content_hash,
                        document_id = excluded.document_id,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (str(resolved), stat.st_size, mtime, digest, staged.document_id),
                )
            result = _prepare_document(ctx, job, staged.document_id)
            with store.connect() as conn:
                conn.execute(
                    "UPDATE knowledge_ingest_files SET status = 'READY', updated_at = datetime('now') WHERE path = ?",
                    (str(resolved),),
                )
            return result

        if action in {"upsert", "ingest_document", "prepare", "stage_prepare"}:
            document_id = str(args.get("document_id") or "").strip() or None
            if document_id and not args.get("content"):
                return _prepare_document(ctx, job, document_id)
            if args.get("content") is not None:
                title = str(args.get("title") or "Untitled").strip() or "Untitled"
                content = str(args.get("content") or "")
                source = str(args.get("source") or "manual").strip() or "manual"
                staged = store.stage_document(
                    document_id=document_id,
                    title=title,
                    content=content,
                    source=source,
                )
                return _prepare_document(ctx, job, staged.document_id)
            if document_id:
                return _prepare_document(ctx, job, document_id)
            raise ValueError("document_id or content required for knowledge.prepare")

        lease_ttl = float(
            ctx.get("lease_ttl_seconds")
            or getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0)
            or 30.0
        )
        return _default_gateway_execute(
            ctx["job_runtime"],
            ctx["job_store"],
            job,
            str(ctx.get("worker_id") or "knowledge_prepare"),
            lease_ttl,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(ctx, job, f"KNOWLEDGE_PREPARE_FAILED: {exc}")


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    cap = str(getattr(job, "capability_id", "") or "")
    if cap == "knowledge.ingest_scan":
        return _handle_ingest_scan_v2(ctx, job)
    if cap in {"knowledge.prepare", "knowledge.ingest_document", "knowledge.ingest_path"}:
        return _handle_prepare(ctx, job)
    lease_ttl = float(
        ctx.get("lease_ttl_seconds")
        or getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0)
        or 30.0
    )
    return _default_gateway_execute(
        ctx["job_runtime"],
        ctx["job_store"],
        job,
        str(ctx.get("worker_id") or "knowledge_prepare"),
        lease_ttl,
    )


def main(argv=None):
    return main_for_pool("knowledge_prepare", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
