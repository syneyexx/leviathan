"""Knowledge prepare pool entrypoint — ``knowledge.prepare`` (gateway path) and the
externalized operator scan ``knowledge.ingest_scan`` (Knowledge V2 ``scan_data_root``).

The scan used to run inline in the FastAPI process (``/api/knowledge/ingest/scan``,
``/api/neuro/absorb``). Under ``externalize_api_runners`` those routes enqueue here so the
Control Plane never blocks on filesystem walks + chunking + embedding.
"""
from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool
from Data.modules.workers.loop import _default_gateway_execute


def _handle_ingest_scan(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    limit = min(max(int(args.get("limit") or 50), 1), 5000)
    try:
        from Data.modules.knowledge import KnowledgeStore

        settings = ctx["settings"]
        store = KnowledgeStore(
            settings.database_path,
            data_root=settings.knowledge.data_root,
            chunk_max_chars=settings.knowledge.chunk_max_chars,
            chunk_overlap=settings.knowledge.chunk_overlap,
        )
        store.initialize()
        docs = store.scan_data_root(limit=limit)
        result = {
            "scanned": len(docs),
            "ingested": len(docs),
            "data_root": str(settings.knowledge.data_root),
            "document_ids": [getattr(d, "document_id", str(d)) for d in docs],
            "executed_via": "knowledge_prepare_worker",
            "truth": {"uses_knowledge_v2_ingest": True, "no_parallel_ingest_pipeline": True},
        }
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    if str(getattr(job, "capability_id", "") or "") == "knowledge.ingest_scan":
        return _handle_ingest_scan(ctx, job)
    lease_ttl = float(ctx.get("lease_ttl_seconds") or getattr(ctx.get("worker_settings"), "lease_ttl_seconds", 30.0) or 30.0)
    return _default_gateway_execute(
        ctx["job_runtime"], ctx["job_store"], job, str(ctx.get("worker_id") or "knowledge_prepare"), lease_ttl
    )


def main(argv=None):
    return main_for_pool("knowledge_prepare", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
