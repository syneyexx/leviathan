"""document_ai worker pool entrypoint — OCR / Document AI execution owner."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool

OCR_CAPABILITIES = frozenset(
    {
        "ocr.extract",
        "document_ai.ocr",
        "document_ai.extract",
        "document_ai.process",
    }
)


def _enqueue_ocr_continue(
    ctx: dict[str, Any],
    *,
    source_id: str,
    project_id: str,
    container_source_id: str | None,
    relative_path: str | None,
    parent_job_id: str | None,
    root_job_id: str | None,
    ocr_job_id: str,
) -> str | None:
    runtime = ctx.get("job_runtime")
    if runtime is None:
        return None
    from Data.modules.source_ingestion.types import CAPABILITY_OCR_CONTINUE

    idem = f"source_ingestion:ocr_continue:{source_id}:{relative_path or ''}:{ocr_job_id}"
    job = runtime.enqueue(
        capability_id=CAPABILITY_OCR_CONTINUE,
        arguments={
            "source_id": source_id,
            "project_id": project_id,
            "container_source_id": container_source_id,
            "relative_path": relative_path,
            "ocr_job_id": ocr_job_id,
        },
        requested_by="document_ai.ocr_complete",
        idempotency_key=idem[:200],
        metadata={
            "source_id": source_id,
            "project_id": project_id,
            "human_title": relative_path or source_id,
            "ocr_job_id": ocr_job_id,
        },
        latency_class="background",
        domain="source_ingestion",
        domain_entity_type="source",
        domain_entity_id=container_source_id or source_id,
        worker_pool="source_ingestion",
        resource_class="CPU_HEAVY",
        parent_job_id=parent_job_id,
        root_job_id=root_job_id or parent_job_id,
    )
    return job.job_id


def _persist_ocr_artifact(
    ctx: dict[str, Any],
    *,
    project_id: str,
    source_id: str,
    text: str,
    provenance: dict[str, Any],
) -> Path:
    from Data.modules.common.atomic import atomic_write_text, ensure_dir
    from Data.backend.config import load_settings

    settings = ctx.get("settings") or load_settings()
    # Prefer explicit corpus roots when available; otherwise derive from job store.
    job_store = ctx.get("job_store")
    base = Path(getattr(settings, "project_root", None) or ".")
    if job_store is not None and getattr(job_store, "path", None):
        base = Path(job_store.path).parent
    try:
        from Data.modules.common.corpus import build_corpus_layout

        corpus = build_corpus_layout(settings).ensure()
        snap_dir = ensure_dir(corpus.research_snapshots / project_id)
        artifact_root = Path(getattr(settings, "project_root", corpus.root)) / "artifacts" / "ocr"
    except Exception:  # noqa: BLE001
        snap_dir = ensure_dir(base / "research" / "snapshots" / project_id)
        artifact_root = ensure_dir(base / "artifacts" / "ocr")
    snapshot = snap_dir / f"{source_id}.ocr.txt"
    atomic_write_text(snapshot, text)
    ensure_dir(artifact_root)
    sidecar = artifact_root / f"{source_id}.json"
    import json

    sidecar.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any]:
    from Data.modules.documents.ocr_backend import OcrRetryClass, get_document_ai_backend
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState
    from Data.modules.research.store import ResearchStore
    from Data.modules.source_ingestion.metrics import ingestion_metrics
    from Data.modules.source_ingestion.types import (
        ERROR_DOCUMENT_AI_UNAVAILABLE,
        ERROR_OCR_UNAVAILABLE,
    )

    capability = str(getattr(job, "capability_id", "") or "")
    args = dict(getattr(job, "arguments", None) or {})
    source_id = str(args.get("source_id") or "")
    project_id = str(args.get("project_id") or "")
    path_raw = str(args.get("path") or "")
    relative_path = str(args.get("relative_path") or path_raw)
    worker_id = str(ctx.get("worker_id") or "")
    store = ctx["job_store"]
    metrics = ingestion_metrics()
    metrics.inc("ocr_requested")

    backend = get_document_ai_backend()
    readiness = backend.probe()
    if readiness.state.value in {"UNAVAILABLE", "MISCONFIGURED"}:
        metrics.inc("ocr_unavailable")
        receipt = {
            "capability_id": capability,
            "source_id": source_id,
            "project_id": project_id,
            "relative_path": relative_path,
            "status": ERROR_OCR_UNAVAILABLE,
            "error_code": ERROR_OCR_UNAVAILABLE,
            "reason": readiness.failure_reason or "OCR backend missing",
            "extracted_text": None,
            "extracted_chars": 0,
            "retry_class": OcrRetryClass.STRUCTURAL_UNAVAILABLE.value,
            "readiness": readiness.public_dict(),
            "truth": {
                "ocr_backend": backend.name(),
                "fabricated": False,
                "executed_inline": False,
                "pool": "document_ai",
                "parent_job_id": getattr(job, "parent_job_id", None),
                "root_job_id": getattr(job, "root_job_id", None),
            },
        }
        if capability.startswith("document_ai."):
            receipt["status"] = ERROR_DOCUMENT_AI_UNAVAILABLE
            receipt["error_code"] = ERROR_DOCUMENT_AI_UNAVAILABLE
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            error=f"{receipt['error_code']}: {receipt['reason']}",
            result=receipt,
        )
        return receipt

    path = Path(path_raw)
    if not path.is_file():
        metrics.inc("ocr_failed")
        receipt = {
            "capability_id": capability,
            "source_id": source_id,
            "status": "OCR_FAILED",
            "error_code": "OCR_FAILED",
            "reason": "input file missing",
            "retry_class": OcrRetryClass.TERMINAL.value,
            "extracted_text": None,
            "extracted_chars": 0,
        }
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            error=receipt["reason"],
            result=receipt,
        )
        return receipt

    native_pages = list(args.get("native_pages") or [])
    extract = backend.extract(path, mime_type=args.get("mime_type"), native_pages=native_pages)
    if not extract.ok:
        if extract.retry_class == OcrRetryClass.STRUCTURAL_UNAVAILABLE:
            metrics.inc("ocr_unavailable")
        else:
            metrics.inc("ocr_failed")
        receipt = {
            "capability_id": capability,
            "source_id": source_id,
            "project_id": project_id,
            "relative_path": relative_path,
            "status": extract.error_code or "OCR_FAILED",
            "error_code": extract.error_code,
            "reason": extract.error_message,
            "retry_class": extract.retry_class.value if extract.retry_class else None,
            "extracted_text": None,
            "extracted_chars": 0,
            "ocr": extract.public_dict(),
            "truth": {
                "ocr_backend": extract.backend_name,
                "fabricated": False,
                "executed_inline": False,
                "pool": "document_ai",
            },
        }
        state = JobState.FAILED
        fenced_transition(
            store,
            job.job_id,
            state,
            worker_id=worker_id,
            error=str(extract.error_message or extract.error_code)[:500],
            result=receipt,
        )
        return receipt

    metrics.inc("ocr_succeeded")
    provenance = {
        "backend": extract.backend_name,
        "backend_version": extract.backend_version,
        "languages": extract.languages,
        "page_count": extract.page_count,
        "ocr_page_count": extract.ocr_page_count,
        "confidence_mean": extract.confidence_mean,
        "started_at": extract.started_at,
        "finished_at": extract.finished_at,
        "input_hash": extract.input_hash,
        "output_text_hash": extract.output_text_hash,
        "parent_job_id": getattr(job, "parent_job_id", None),
        "root_job_id": getattr(job, "root_job_id", None),
        "source_id": source_id,
        "relative_path": relative_path,
        "pages": extract.public_dict().get("pages"),
    }
    snapshot_path = _persist_ocr_artifact(
        ctx,
        project_id=project_id,
        source_id=source_id,
        text=extract.text,
        provenance=provenance,
    )

    settings = ctx.get("settings")
    if settings is None:
        from Data.backend.config import load_settings

        settings = load_settings()
    # Prefer the worker JobStore DB (same CONTROL domain) so OCR continuation
    # updates the source that source_ingestion owns — not a divergent settings path.
    db_path = Path(getattr(store, "path", None) or getattr(settings, "database_path", ""))
    research = ResearchStore(db_path)
    research.initialize()
    src = research.get_source(source_id)
    if src is not None:
        prov = dict(src.provenance or {})
        prov["ocr"] = provenance
        prov["ocr_snapshot_path"] = str(snapshot_path)
        from Data.modules.research.types import BrainStatus, ParseStatus, ResearchSource

        updated = ResearchSource(
            source_id=src.source_id,
            project_id=src.project_id,
            source_type=src.source_type,
            created_at=src.created_at,
            original_uri=src.original_uri,
            canonical_uri=src.canonical_uri,
            title=src.title,
            author=src.author,
            published_at=src.published_at,
            fetched_at=src.fetched_at,
            content_hash=extract.output_text_hash,
            mime_type=src.mime_type,
            snapshot_path=str(snapshot_path),
            parse_status=ParseStatus.OK,
            parser="ocr",
            brain_status=BrainStatus.PENDING,
            brain_document_id=src.brain_document_id,
            brain_error=None,
            provenance=prov,
            metadata={**dict(src.metadata or {}), "ocr_completed": True},
        )
        research.save_source(updated)

    continue_job_id = _enqueue_ocr_continue(
        ctx,
        source_id=source_id,
        project_id=project_id,
        container_source_id=args.get("container_source_id"),
        relative_path=relative_path,
        parent_job_id=job.job_id,
        root_job_id=getattr(job, "root_job_id", None) or getattr(job, "parent_job_id", None),
        ocr_job_id=job.job_id,
    )

    receipt = {
        "capability_id": capability,
        "source_id": source_id,
        "project_id": project_id,
        "relative_path": relative_path,
        "status": "SUCCESS",
        "error_code": None,
        "extracted_text": extract.text[:2000],
        "extracted_chars": len(extract.text),
        "snapshot_path": str(snapshot_path),
        "ocr": extract.public_dict(),
        "ocr_continue_job_id": continue_job_id,
        "truth": {
            "ocr_backend": extract.backend_name,
            "fabricated": False,
            "executed_inline": False,
            "pool": "document_ai",
            "parent_job_id": getattr(job, "parent_job_id", None),
            "root_job_id": getattr(job, "root_job_id", None),
        },
    }
    fenced_transition(
        store,
        job.job_id,
        JobState.COMPLETED,
        worker_id=worker_id,
        result=receipt,
    )
    return receipt


def main(argv=None):
    return main_for_pool("document_ai", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
