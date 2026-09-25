"""Knowledge prepare pool entrypoint — ``knowledge.prepare`` and ``knowledge.ingest_scan``.

Heavy filesystem walks, chunking, embedding prep, and legacy content backfill run here —
never inline in the FastAPI control plane when externalization is enabled.
"""
from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool
from Data.modules.workers.loop import _default_gateway_execute


def _knowledge_store(ctx: dict[str, Any]) -> Any:
    from Data.modules.knowledge import KnowledgeStore

    settings = ctx["settings"]
    store = KnowledgeStore(
        settings.database_path,
        data_root=settings.knowledge.data_root,
        chunk_max_chars=settings.knowledge.chunk_max_chars,
        chunk_overlap=settings.knowledge.chunk_overlap,
    )
    store.initialize_schema()
    return store


def _handle_ingest_scan(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    limit = min(max(int(args.get("limit") or 50), 1), 5000)
    try:
        store = _knowledge_store(ctx)
        docs = store.scan_data_root(limit=limit)
        result = {
            "scanned": len(docs),
            "ingested": len(docs),
            "data_root": str(ctx["settings"].knowledge.data_root),
            "document_ids": [getattr(d, "document_id", str(d)) for d in docs],
            "executed_via": "knowledge_prepare_worker",
            "truth": {"uses_knowledge_v2_ingest": True, "no_parallel_ingest_pipeline": True},
        }
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def _handle_prepare(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    action = str(args.get("action") or "prepare").strip().lower()
    store = _knowledge_store(ctx)
    try:
        if action in {"backfill", "content_backfill"}:
            result = store.backfill_content(limit=int(args.get("limit") or 50))
            result["action"] = action
            result["executed_via"] = "knowledge_prepare_worker"
            ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
            return result

        if action in {"ingest_path", "path"}:
            path = str(args.get("path") or "").strip()
            if not path:
                raise ValueError("path is required for ingest_path")
            resolved = store.resolve_under_data_root(path)
            record = store.ingest_file(resolved)
            result = {
                "action": action,
                "ingested": record is not None,
                "document": record.public_dict() if record else None,
                "reason": None if record else "unchanged",
                "executed_via": "knowledge_prepare_worker",
            }
            ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
            return result

        if action in {"upsert", "ingest_document", "prepare", "stage_prepare"}:
            document_id = str(args.get("document_id") or "").strip() or None
            # Prefer staged document_id (content already in KnowledgeStore).
            if document_id and not args.get("content"):
                record = store.prepare_staged_document(document_id)
            elif args.get("content") is not None:
                title = str(args.get("title") or "Untitled").strip() or "Untitled"
                content = str(args.get("content") or "")
                source = str(args.get("source") or "manual").strip() or "manual"
                if document_id:
                    staged = store.stage_document(
                        document_id=document_id,
                        title=title,
                        content=content,
                        source=source,
                    )
                    record = store.prepare_staged_document(staged.document_id)
                else:
                    record = store.upsert_document(title=title, content=content, source=source)
            elif document_id:
                record = store.prepare_staged_document(document_id)
            else:
                raise ValueError("document_id or content required for knowledge.prepare")
            result = {
                "action": action,
                "document": record.public_dict(),
                "document_id": record.document_id,
                "status": getattr(getattr(record, "status", None), "value", None)
                or str(getattr(record, "status", "")),
                "executed_via": "knowledge_prepare_worker",
            }
            ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
            return result

        # Unknown prepare action — fall through to gateway for artifact_id style jobs.
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
        ctx["job_store"].transition(
            job.job_id,
            JobState.FAILED,
            error=f"KNOWLEDGE_PREPARE_FAILED: {exc}"[:500],
        )
        return {"error": str(exc)}


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    cap = str(getattr(job, "capability_id", "") or "")
    if cap == "knowledge.ingest_scan":
        return _handle_ingest_scan(ctx, job)
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
