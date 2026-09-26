"""Knowledge / atlas / deep-recall / why / ingest HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, HTTPException, Query
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
    evaluation_externalize_fn: Callable[[], bool],
    enqueue_ingest_scan_fn: Callable[..., dict] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["knowledge"])
    enqueue_ingest_scan = enqueue_ingest_scan_fn or make_enqueue_ingest_scan(
        job_runtime, settings
    )

    @router.get("/api/knowledge")
    def list_knowledge() -> dict:
        return {"documents": [doc.public_dict() for doc in knowledge.list_documents()]}

    @router.post("/api/knowledge")
    def write_knowledge(payload: KnowledgeWrite) -> dict:
        title = payload.title.strip()
        content = payload.content.strip()
        source = payload.source.strip()
        if evaluation_externalize_fn():
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
        document = knowledge.upsert_document(
            document_id=payload.id,
            title=title,
            content=content,
            source=source,
        )
        return {"document": document.public_dict()}

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
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if evaluation_externalize_fn():
            job = job_runtime.enqueue(
                capability_id="knowledge.prepare",
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
        try:
            record = knowledge.ingest_file(resolved)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if record is None:
            return {"ingested": False, "reason": "unchanged"}
        return {
            "ingested": True,
            "document": record.public_dict(),
            "chunks": [chunk.public_dict() for chunk in knowledge.list_chunks(record.document_id)],
        }

    @router.post("/api/knowledge/ingest/scan")
    def ingest_knowledge_scan(limit: int = 50) -> dict:
        safe_limit = min(max(limit, 1), 500)
        if evaluation_externalize_fn():
            return enqueue_ingest_scan(safe_limit, requested_by="api.knowledge.ingest_scan")
        # Developer/testing mode only — never silent fallback when externalization is on.
        try:
            docs = knowledge.scan_data_root(limit=safe_limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "scanned": len(docs),
            "data_root": str(settings.knowledge.data_root),
            "documents": [doc.public_dict() for doc in docs],
        }

    return router
