"""Knowledge / atlas / deep-recall / why / ingest HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from Data.modules.knowledge import DeepRecallRequest, DeepRecallService, RetrievalQuery


class KnowledgeWrite(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=250_000)
    source: str = Field(default="manual", min_length=1, max_length=240)


class AtlasWrite(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=20_000)
    scale: str = Field(default="thread", min_length=1, max_length=64)
    scope: str = Field(default="", max_length=500)
    entities: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    evidence_record_refs: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AtlasRevise(BaseModel):
    summary: str | None = None
    title: str | None = None
    revision_reason: str = Field(default="revised", max_length=500)
    unresolved_questions: list[str] | None = None
    contradictions: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_record_refs: list[str] | None = None


class DeepRecallBody(BaseModel):
    current_question: str = Field(min_length=1, max_length=4000)
    remembered_gist: str = Field(default="", max_length=4000)
    missing_detail: str = Field(default="", max_length=4000)
    required_precision: str = Field(default="normal", max_length=32)
    maximum_context_budget: int | None = Field(default=None, ge=64, le=20_000)
    hydrate_limit: int = Field(default=5, ge=1, le=50)


class WhyAssimilateBody(BaseModel):
    observation: str = Field(min_length=1, max_length=8000)
    parent_ref: str | None = None
    child_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    resemblance_notes: str = Field(default="", max_length=4000)
    residue: str = Field(default="", max_length=4000)
    exclude_child: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class KnowledgeIngestPath(BaseModel):
    path: str = Field(min_length=1, max_length=4000)


def make_enqueue_ingest_scan(job_runtime: Any, settings: Any) -> Callable[..., dict]:
    """F0-lite: heavy ModelData scan runs on the knowledge_prepare pool, never inline."""

    def _enqueue_ingest_scan(
        limit: int, *, requested_by: str, extra_metadata: dict | None = None
    ) -> dict:
        import uuid

        job = job_runtime.enqueue(
            capability_id="knowledge.ingest_scan",
            arguments={"limit": limit},
            requested_by=requested_by,
            domain="knowledge",
            domain_entity_type="knowledge_scan",
            domain_entity_id=str(settings.knowledge.data_root),
            worker_pool="knowledge_prepare",
            resource_class="CPU_HEAVY",
            latency_class="background",
            idempotency_key=f"knowledge:ingest_scan:{uuid.uuid4().hex[:8]}",
            metadata={"limit": limit, **dict(extra_metadata or {})},
        )
        return {
            "job": job.public_dict(),
            "queued": True,
            "scanned": None,
            "data_root": str(settings.knowledge.data_root),
            "documents": [],
            "truth": {"executed_via": "knowledge_prepare_worker", "result_in_job": True},
        }

    return _enqueue_ingest_scan


def build_knowledge_router(
    *,
    settings: Any,
    knowledge: Any,
    retriever: Any,
    job_runtime: Any,
    atlas_store: Any,
    deep_recall_service: Any,
    why_library: Any,
    workers_externalize_fn: Callable[[], bool] | None = None,
    evaluation_externalize_fn: Callable[[], bool] | None = None,
    enqueue_ingest_scan_fn: Callable[..., dict] | None = None,
    source_ingestion: Any | None = None,
    research_store: Any | None = None,
) -> APIRouter:
    """Knowledge HTTP surface — staging/enqueue/read only when workers are externalized.

    ``workers_externalize_fn`` is the canonical predicate. ``evaluation_externalize_fn``
    remains accepted as a deprecated alias for call-site compatibility.

    ``source_ingestion`` is the optional SourceIngestionService used by Knowledge
    Library uploads (same pipeline as Research — no second uploader).
    """
    from Data.modules.knowledge.execution_gate import (
        refuse_inline_knowledge,
        resolve_externalize_fn,
    )

    router = APIRouter(tags=["knowledge"])
    enqueue_ingest_scan = enqueue_ingest_scan_fn or make_enqueue_ingest_scan(
        job_runtime, settings
    )
    externalize_fn = resolve_externalize_fn(
        workers_externalize_fn or evaluation_externalize_fn,
        settings=settings,
    )

    def _require_source_ingestion() -> Any:
        if source_ingestion is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "SOURCE_INGESTION_UNAVAILABLE",
                    "message": "SourceIngestionService is not bound to Knowledge routes",
                },
            )
        return source_ingestion

    @router.get("/api/knowledge")
    def list_knowledge() -> dict:
        return {"documents": [doc.public_dict() for doc in knowledge.list_documents()]}

    @router.post("/api/knowledge")
    def write_knowledge(payload: KnowledgeWrite) -> dict:
        title = payload.title.strip()
        content = payload.content.strip()
        source = payload.source.strip()
        if not externalize_fn():
            # Explicit non-externalized mode (tests / operators) — still prefer stage+prepare
            # style unless ALLOW_INLINE is set; never a silent production fallback.
            from Data.modules.knowledge.execution_gate import inline_execution_explicitly_allowed

            if not inline_execution_explicitly_allowed():
                refuse_inline_knowledge(reason="externalize_disabled_without_inline_allow")
            document = knowledge.upsert_document(
                document_id=payload.id,
                title=title,
                content=content,
                source=source,
            )
            return {"document": document.public_dict(), "queued": False}
        staged = knowledge.stage_document(
            document_id=payload.id,
            title=title,
            content=content,
            source=source,
        )
        job = job_runtime.enqueue(
            capability_id="knowledge.prepare",
            arguments={
                "action": "prepare",
                "document_id": staged.document_id,
            },
            requested_by="api.knowledge.write",
            domain="knowledge",
            domain_entity_type="document",
            domain_entity_id=staged.document_id,
            worker_pool="knowledge_prepare",
            resource_class="CPU_HEAVY",
            latency_class="interactive",
            idempotency_key=f"knowledge:prepare:{staged.document_id}:{staged.content_hash or 'x'}",
            metadata={
                "human_title": title,
                "document_id": staged.document_id,
                "filename": title,
            },
        )
        return {
            "queued": True,
            "job": job.public_dict(),
            "document": staged.public_dict(),
            "status": "INDEXING",
            "truth": {"executed_via": "knowledge_prepare_worker", "chunking_deferred": True},
        }

    @router.get("/api/knowledge/search")
    def search_knowledge(
        q: Annotated[str, Query(min_length=1, max_length=4000)],
        limit: int = 5,
        source: str | None = None,
    ) -> dict:
        safe_limit = min(max(limit, 1), 20)
        hits = retriever.search(RetrievalQuery(text=q, limit=safe_limit, source=source))
        return {
            "hits": [hit.public_dict() for hit in hits],
            # Backward-compatible document projection for older clients.
            "documents": [hit.as_context_document() for hit in hits],
        }

    @router.get("/api/knowledge/atlas")
    def list_atlas(
        q: Annotated[str, Query(max_length=4000)] = "",
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict:
        if not settings.features.rag_v3:
            return {
                "available": False,
                "reason": "LEVIATHAN_FEATURE_RAG_V3=false",
                "records": [],
            }
        records = atlas_store.search(q, limit=limit) if q.strip() else atlas_store.search("", limit=limit)
        return {"available": True, "records": [item.public_dict() for item in records]}

    @router.post("/api/knowledge/atlas")
    def create_atlas(payload: AtlasWrite) -> dict:
        if not settings.features.rag_v3:
            raise HTTPException(status_code=503, detail="RAG V3 / atlas unavailable")
        try:
            record = atlas_store.create(
                title=payload.title,
                summary=payload.summary,
                scale=payload.scale,
                scope=payload.scope,
                entities=payload.entities,
                projects=payload.projects,
                evidence_record_refs=payload.evidence_record_refs,
                unresolved_questions=payload.unresolved_questions,
                contradictions=payload.contradictions,
                confidence=payload.confidence,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"record": record.public_dict()}

    @router.post("/api/knowledge/atlas/{atlas_id}/revise")
    def revise_atlas(atlas_id: str, payload: AtlasRevise) -> dict:
        if not settings.features.rag_v3:
            raise HTTPException(status_code=503, detail="RAG V3 / atlas unavailable")
        record = atlas_store.revise(
            atlas_id,
            summary=payload.summary,
            title=payload.title,
            revision_reason=payload.revision_reason,
            unresolved_questions=payload.unresolved_questions,
            contradictions=payload.contradictions,
            confidence=payload.confidence,
            evidence_record_refs=payload.evidence_record_refs,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Atlas record not found")
        return {"record": record.public_dict()}

    @router.post("/api/knowledge/deep-recall")
    def run_deep_recall(payload: DeepRecallBody) -> dict:
        if not settings.features.deep_recall:
            disabled = DeepRecallService(
                knowledge=knowledge,
                atlas=atlas_store,
                retriever=retriever,
                db_path=settings.database_path,
                enabled=False,
            )
            result = disabled.recall(DeepRecallRequest(current_question=payload.current_question))
            return {
                "available": False,
                "reason": "LEVIATHAN_FEATURE_DEEP_RECALL=false",
                "result": result.public_dict(),
            }
        result = deep_recall_service.recall(
            DeepRecallRequest(
                current_question=payload.current_question,
                remembered_gist=payload.remembered_gist,
                missing_detail=payload.missing_detail,
                required_precision=payload.required_precision,
                maximum_context_budget=payload.maximum_context_budget
                or settings.knowledge.deep_recall_budget,
                hydrate_limit=payload.hydrate_limit,
            )
        )
        return {"available": result.available, "result": result.public_dict()}

    @router.get("/api/knowledge/deep-recall/logs")
    def deep_recall_logs(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
        return {"logs": deep_recall_service.recent_logs(limit=limit)}

    @router.post("/api/knowledge/why")
    def assimilate_why(payload: WhyAssimilateBody) -> dict:
        if not settings.features.why_library:
            return {"available": False, "reason": "LEVIATHAN_FEATURE_WHY_LIBRARY=false", "record": None}
        record = why_library.assimilate(
            observation=payload.observation,
            parent_ref=payload.parent_ref,
            child_ref=payload.child_ref,
            evidence_refs=payload.evidence_refs,
            resemblance_notes=payload.resemblance_notes,
            residue=payload.residue,
            exclude_child=payload.exclude_child,
            confidence=payload.confidence,
        )
        return {"available": True, "record": record.public_dict() if record else None}

    @router.get("/api/knowledge/why")
    def list_why(
        q: Annotated[str, Query(max_length=4000)] = "",
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict:
        if not settings.features.why_library:
            return {"available": False, "reason": "LEVIATHAN_FEATURE_WHY_LIBRARY=false", "records": []}
        records = why_library.search(q, limit=limit) if q.strip() else why_library.list_recent(limit=limit)
        return {"available": True, "records": [item.public_dict() for item in records]}

    @router.get("/api/knowledge/health")
    def knowledge_index_health() -> dict:
        """Bounded index health inspection — never repairs/rebuilds."""
        if hasattr(knowledge, "index_health"):
            return {"health": knowledge.index_health()}
        return {"health": {"available": False}}

    @router.get("/api/knowledge/library/overview")
    def knowledge_library_overview() -> dict:
        """Bounded Library KPIs — totals/types/tags/embedding coverage/latest ingest."""
        if not hasattr(knowledge, "library_overview"):
            raise HTTPException(status_code=501, detail="Library overview unavailable")
        # Opportunistic idempotent backfill for legacy rows (bounded, cheap).
        if hasattr(knowledge, "backfill_library_metadata"):
            try:
                knowledge.backfill_library_metadata(limit=500)
            except Exception:  # noqa: BLE001
                pass
        overview = knowledge.library_overview()
        # Prefer durable SourceIngestion latest event when SI is bound.
        if source_ingestion is not None and hasattr(source_ingestion, "list_recent_ingestions"):
            try:
                from Data.modules.source_ingestion.types import CALLER_CONTEXT_KNOWLEDGE_LIBRARY

                recent = source_ingestion.list_recent_ingestions(
                    caller_context=CALLER_CONTEXT_KNOWLEDGE_LIBRARY,
                    limit=1,
                    offset=0,
                )
                items = recent.get("items") or []
                if items:
                    first = items[0]
                    overview = {
                        **overview,
                        "latest_ingestion": {
                            "source_id": first.get("source_id"),
                            "title": first.get("filename"),
                            "created_at": first.get("created_at"),
                            "updated_at": first.get("created_at"),
                            "status": first.get("status"),
                            "source": "source_ingestion",
                            "size_bytes": first.get("size_bytes"),
                            "kind": "source_ingestion",
                            "progress_pct": first.get("progress_pct"),
                            "measured": first.get("measured"),
                        },
                        "truth": {
                            **dict(overview.get("truth") or {}),
                            "latest_ingestion_from_source_ingestion": True,
                        },
                    }
            except Exception:  # noqa: BLE001
                pass
        return {"overview": overview}

    @router.get("/api/knowledge/library")
    def knowledge_library_list(
        q: Annotated[str, Query(max_length=4000)] = "",
        type: Annotated[str, Query(max_length=64)] = "",
        tag: Annotated[str, Query(max_length=64)] = "",
        status: Annotated[str, Query(max_length=32)] = "",
        date_from: Annotated[str, Query(max_length=64)] = "",
        date_to: Annotated[str, Query(max_length=64)] = "",
        sort: Annotated[str, Query(max_length=32)] = "",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        cursor: Annotated[str, Query(max_length=64)] = "",
    ) -> dict:
        """Bounded Knowledge Library query — summary rows only."""
        if not hasattr(knowledge, "query_library"):
            raise HTTPException(status_code=501, detail="Library query unavailable")
        try:
            result = knowledge.query_library(
                q=q or None,
                library_type=type or None,
                tag=tag or None,
                status=status or None,
                date_from=date_from or None,
                date_to=date_to or None,
                sort=sort or None,
                limit=limit,
                offset=offset,
                cursor=cursor or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result

    @router.get("/api/knowledge/library/ingestion/capabilities")
    def knowledge_library_ingestion_capabilities() -> dict:
        """Advertised SourceIngestion format/upload limits for Library UI."""
        from Data.modules.source_ingestion.capabilities import build_format_capabilities
        from Data.modules.source_ingestion.settings import load_source_ingestion_settings

        return build_format_capabilities(load_source_ingestion_settings())

    @router.post("/api/knowledge/library/ingestion/upload")
    async def knowledge_library_upload(file: UploadFile = File(...)) -> dict:
        """Stream upload into SourceIngestionService (Knowledge Library caller).

        Heavy parse/ZIP/OCR work runs on source_ingestion workers — never file.text().
        """
        si = _require_source_ingestion()
        from Data.modules.research.types import ResearchError

        try:
            result = si.accept_knowledge_library_upload(
                filename=file.filename or "upload.bin",
                stream=file.file,
                content_type=file.content_type,
            )
        except ResearchError as exc:
            raise HTTPException(
                status_code=int(getattr(exc, "http_status", None) or 422),
                detail={
                    "error": getattr(exc, "code", None) or "SOURCE_INGESTION_ERROR",
                    "message": str(exc),
                    "details": getattr(exc, "details", None) or {},
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001
            # SourceIngestion may raise IngestionError for size limits.
            code = getattr(exc, "code", None) or "SOURCE_INGESTION_ERROR"
            status = int(getattr(exc, "http_status", None) or 422)
            raise HTTPException(
                status_code=status,
                detail={"error": code, "message": str(exc)[:500]},
            ) from exc
        return result

    @router.get("/api/knowledge/library/ingestion/recent")
    def knowledge_library_recent_ingestions(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> dict:
        si = _require_source_ingestion()
        from Data.modules.research.types import ResearchError
        from Data.modules.source_ingestion.types import CALLER_CONTEXT_KNOWLEDGE_LIBRARY

        try:
            return si.list_recent_ingestions(
                caller_context=CALLER_CONTEXT_KNOWLEDGE_LIBRARY,
                limit=limit,
                offset=offset,
            )
        except ResearchError as exc:
            raise HTTPException(
                status_code=int(getattr(exc, "http_status", None) or 422),
                detail={"error": getattr(exc, "code", None), "message": str(exc)},
            ) from exc

    @router.get("/api/knowledge/library/ingestion/{source_id}")
    def knowledge_library_ingestion_status(source_id: str) -> dict:
        si = _require_source_ingestion()
        progress = si.get_status(source_id)
        payload = progress.public_dict() if hasattr(progress, "public_dict") else dict(progress)
        return {"source_id": source_id, "progress": payload}

    @router.post("/api/knowledge/library/ingestion/{source_id}/cancel")
    def knowledge_library_ingestion_cancel(source_id: str) -> dict:
        si = _require_source_ingestion()
        return {"progress": si.cancel(source_id)}

    @router.post("/api/knowledge/library/ingestion/{source_id}/retry")
    def knowledge_library_ingestion_retry(
        source_id: str,
        failed_only: Annotated[bool, Query()] = True,
    ) -> dict:
        si = _require_source_ingestion()
        return si.retry(source_id, failed_only=failed_only)

    @router.post("/api/knowledge/library/ingestion/{source_id}/brain-retry")
    def knowledge_library_ingestion_brain_retry(source_id: str) -> dict:
        si = _require_source_ingestion()
        if not hasattr(si, "retry_brain"):
            raise HTTPException(status_code=501, detail="Brain retry unavailable")
        return si.retry_brain(source_id)

    @router.get("/api/knowledge/library/{document_id}")
    def knowledge_library_document(document_id: str) -> dict:
        """Library summary for one document (no content/chunks)."""
        if not hasattr(knowledge, "get_library_document_summary"):
            raise HTTPException(status_code=501, detail="Library summary unavailable")
        summary = knowledge.get_library_document_summary(document_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return {"document": summary}

    @router.post("/api/knowledge/library/{document_id}/tags")
    def knowledge_library_set_tags(document_id: str, payload: dict[str, Any]) -> dict:
        """Replace or append document tags via canonical Knowledge metadata."""
        if not hasattr(knowledge, "set_document_tags"):
            raise HTTPException(status_code=501, detail="Library tags unavailable")
        tags_raw = payload.get("tags")
        if not isinstance(tags_raw, list):
            raise HTTPException(status_code=422, detail="tags must be a list of strings")
        mode = str(payload.get("mode") or "replace").strip().lower()
        try:
            if mode == "add" and hasattr(knowledge, "add_document_tags"):
                tags = knowledge.add_document_tags(document_id, [str(t) for t in tags_raw])
            else:
                tags = knowledge.set_document_tags(document_id, [str(t) for t in tags_raw])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Knowledge document not found") from exc
        return {"document_id": document_id, "tags": tags, "mode": mode}

    @router.get("/api/knowledge/library/{document_id}/preview")
    def knowledge_library_preview(
        document_id: str,
        max_chars: Annotated[int, Query(ge=256, le=50_000)] = 8000,
    ) -> dict:
        """Bounded preview metadata/text. Binary/PDF clients use /content URL."""
        if not hasattr(knowledge, "bounded_text_preview"):
            raise HTTPException(status_code=501, detail="Preview unavailable")
        preview = knowledge.bounded_text_preview(document_id, max_chars=max_chars)
        if preview is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        summary = (
            knowledge.get_library_document_summary(document_id)
            if hasattr(knowledge, "get_library_document_summary")
            else None
        )
        mime = (preview.get("mime_type") or (summary or {}).get("mime_type") or "").lower()
        kind = "text"
        if mime.startswith("image/"):
            kind = "image"
        elif mime == "application/pdf" or mime.endswith("/pdf"):
            kind = "pdf"
        elif "parquet" in mime or mime in {"text/csv", "application/json"}:
            kind = "table"
        preview = {**preview, "preview_kind": kind}
        # Provide secure content URL hint — never a filesystem path.
        preview["content_url"] = f"/api/knowledge/library/{document_id}/content"
        preview["download_url"] = f"/api/knowledge/library/{document_id}/download"
        return {"preview": preview, "document": summary}

    @router.get("/api/knowledge/library/{document_id}/content")
    def knowledge_library_content(document_id: str) -> FileResponse:
        """Stream original artifact bytes for PDF/image preview (path-safe)."""
        return _library_download_response(document_id, inline=True)

    @router.get("/api/knowledge/library/{document_id}/download")
    def knowledge_library_download(document_id: str) -> FileResponse:
        """Stream original artifact as attachment (path-safe)."""
        return _library_download_response(document_id, inline=False)

    def _library_download_response(document_id: str, *, inline: bool) -> FileResponse:
        if not hasattr(knowledge, "resolve_downloadable_artifact"):
            raise HTTPException(status_code=501, detail="Download unavailable")
        sources_root = None
        if source_ingestion is not None:
            sources_root = getattr(source_ingestion, "sources_root", None)
        rs = research_store
        if rs is None and source_ingestion is not None:
            rs = getattr(source_ingestion, "research", None)
        resolved = knowledge.resolve_downloadable_artifact(
            document_id,
            research_store=rs,
            sources_root=sources_root,
        )
        if resolved is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        path = resolved.get("path")
        if path is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": resolved.get("error") or "RAW_ARTIFACT_UNAVAILABLE",
                    "message": "No downloadable original artifact for this source",
                },
            )
        filename = str(resolved.get("filename") or f"{document_id}.bin")
        mime = str(resolved.get("mime_type") or "application/octet-stream")
        disposition = "inline" if inline else "attachment"
        return FileResponse(
            path=str(path),
            media_type=mime,
            filename=filename,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/api/knowledge/library/{document_id}/content-chunks")
    def knowledge_library_content_chunks(
        document_id: str,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> dict:
        if not hasattr(knowledge, "list_document_content_chunks"):
            raise HTTPException(status_code=501, detail="Content chunks unavailable")
        payload = knowledge.list_document_content_chunks(
            document_id, offset=offset, limit=limit
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return payload

    @router.get("/api/knowledge/library/{document_id}/embeddings")
    def knowledge_library_embeddings(document_id: str) -> dict:
        if not hasattr(knowledge, "document_embedding_status"):
            raise HTTPException(status_code=501, detail="Embedding status unavailable")
        status = knowledge.document_embedding_status(document_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return {"embeddings": status}

    @router.get("/api/knowledge/library/{document_id}/relations")
    def knowledge_library_relations(
        document_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict:
        if not hasattr(knowledge, "list_document_relations"):
            raise HTTPException(status_code=501, detail="Relations unavailable")
        payload = knowledge.list_document_relations(document_id, limit=limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return payload

    @router.get("/api/knowledge/library/{document_id}/related")
    def knowledge_library_related(
        document_id: str,
        limit: Annotated[int, Query(ge=1, le=40)] = 12,
    ) -> dict:
        if not hasattr(knowledge, "list_related_library_sources"):
            raise HTTPException(status_code=501, detail="Related sources unavailable")
        payload = knowledge.list_related_library_sources(
            document_id, limit=limit, retriever=retriever
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return payload

    @router.get("/api/knowledge/{document_id}")
    def get_knowledge_document(document_id: str) -> dict:
        document = knowledge.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return {
            "document": document.public_dict(),
            "chunks": [chunk.public_dict() for chunk in knowledge.list_chunks(document_id)],
        }

    @router.delete("/api/knowledge/{document_id}")
    def delete_knowledge(document_id: str) -> dict:
        if not knowledge.delete_document(document_id):
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return {"deleted": True, "id": document_id}

    @router.post("/api/knowledge/ingest/path")
    def ingest_knowledge_path(payload: KnowledgeIngestPath) -> dict:
        try:
            resolved = knowledge.resolve_under_data_root(payload.path.strip())
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": "KNOWLEDGE_PATH_INVALID", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "KNOWLEDGE_PATH_INVALID", "message": str(exc)},
            ) from exc
        if not externalize_fn():
            from Data.modules.knowledge.execution_gate import inline_execution_explicitly_allowed

            if not inline_execution_explicitly_allowed():
                refuse_inline_knowledge(reason="externalize_disabled_without_inline_allow")
            try:
                record = knowledge.ingest_file(resolved)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if record is None:
                return {"ingested": False, "reason": "unchanged", "queued": False}
            return {
                "ingested": True,
                "queued": False,
                "document": record.public_dict(),
                "chunks": [chunk.public_dict() for chunk in knowledge.list_chunks(record.document_id)],
            }
        job = job_runtime.enqueue(
            capability_id="knowledge.ingest_path",
            arguments={"action": "ingest_path", "path": str(resolved)},
            requested_by="api.knowledge.ingest_path",
            domain="knowledge",
            domain_entity_type="path",
            domain_entity_id=str(resolved),
            worker_pool="knowledge_prepare",
            resource_class="IO_HEAVY",
            latency_class="background",
            idempotency_key=f"knowledge:ingest_path:{resolved}",
            metadata={"human_title": resolved.name, "filename": resolved.name, "path": str(resolved)},
        )
        return {
            "queued": True,
            "job": job.public_dict(),
            "path": str(resolved),
            "truth": {"executed_via": "knowledge_prepare_worker"},
        }

    @router.post("/api/knowledge/ingest/scan")
    def ingest_knowledge_scan(limit: int = 50) -> dict:
        safe_limit = min(max(limit, 1), 500)
        if not externalize_fn():
            from Data.modules.knowledge.execution_gate import inline_execution_explicitly_allowed

            if not inline_execution_explicitly_allowed():
                refuse_inline_knowledge(reason="externalize_disabled_without_inline_allow")
            try:
                docs = knowledge.scan_data_root(limit=safe_limit)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {
                "scanned": len(docs),
                "queued": False,
                "data_root": str(settings.knowledge.data_root),
                "documents": [doc.public_dict() for doc in docs],
            }
        return enqueue_ingest_scan(safe_limit, requested_by="api.knowledge.ingest_scan")

    class KnowledgeReconcileBody(BaseModel):
        dry_run: bool = True
        apply: bool = False
        limit: int = Field(default=100, ge=1, le=5000)

    @router.post("/api/knowledge/reconcile")
    def reconcile_knowledge(payload: KnowledgeReconcileBody | None = None) -> dict:
        """Enqueue Knowledge semantic reconciliation (knowledge_prepare).

        Dry-run diagnosis is the default. Apply repairs only when apply=true
        and dry_run=false. Never mutates merely by opening a health page.
        """
        body = payload or KnowledgeReconcileBody()
        if evaluation_externalize_fn():
            dry_run = bool(body.dry_run) and not bool(body.apply)
            job = job_runtime.enqueue(
                capability_id="knowledge.reconcile",
                arguments={
                    "dry_run": dry_run,
                    "apply": bool(body.apply) and not dry_run,
                    "limit": body.limit,
                },
                requested_by="api.knowledge.reconcile",
                domain="knowledge",
                worker_pool="knowledge_prepare",
                resource_class="CPU_HEAVY",
                latency_class="background",
                metadata={"execution_class": "EXTERNAL_REQUIRED"},
            )
            return {
                "queued": True,
                "job": job.public_dict(),
                "job_id": job.job_id,
                "dry_run": dry_run,
                "truth": {
                    "executed_via": "knowledge_prepare_worker",
                    "diagnosis_is_not_mutation": dry_run,
                },
            }
        # In-process diagnosis only when externalize off (tests).
        diagnosis = knowledge.diagnose_reconciliation(limit=body.limit)
        result: dict[str, Any] = {"queued": False, "diagnosis": diagnosis, "applied": False}
        if body.apply and not body.dry_run:
            result["repair"] = knowledge.backfill_content(limit=body.limit)
            result["applied"] = True
            result["verification"] = knowledge.diagnose_reconciliation(limit=body.limit)
        return result

    return router
