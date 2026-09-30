"""Durable memory HTTP routes — control plane for Geheugen V2."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from Data.modules.memory import MemoryKind, MemoryScope, MemoryStatus
from Data.modules.memory.sources import actor_from_record, normalize_source


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: str = "NOTE"
    source: str = "manual"
    trust: str = "explicit"
    tags: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    run_id: str | None = None
    scope: str | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    priority: float | None = None
    metadata: dict[str, Any] | None = None


class MemoryPatchRequest(BaseModel):
    tags: list[str] | None = None
    priority: float | None = Field(default=None, ge=0.0, le=1.0)
    valid_until: str | None = None
    clear_valid_until: bool = False
    metadata_patch: dict[str, Any] | None = None


class MemoryCorrectRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: str | None = None
    trust: str = "explicit"
    tags: list[str] | None = None


class MemoryConsolidateRequest(BaseModel):
    scope: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)
    min_cluster_size: int = Field(default=2, ge=2, le=50)
    persist: bool = True


class MemoryReindexRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    only_missing: bool = False


class MemoryProcessingPatch(BaseModel):
    embeddings_enabled: bool | None = None
    summarization_enabled: bool | None = None
    entity_extraction_enabled: bool | None = None
    brain_projection_enabled: bool | None = None
    duplicate_detection_enabled: bool | None = None


class MemoryFromConversationRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=20_000)
    kind: str = "EPISODIC"
    trust: str = "explicit"
    tags: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    from_assistant: bool = False


def _runners_externalized() -> bool:
    ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
    if ext in {"1", "true", "yes", "on"}:
        return True
    if ext in {"0", "false", "no", "off"}:
        return False
    try:
        from Data.modules.workers.settings import load_worker_settings

        return bool(load_worker_settings().externalize_api_runners)
    except Exception:  # noqa: BLE001
        return False


def _enqueue_memory_job(
    job_runtime: Any,
    *,
    capability_id: str,
    arguments: dict[str, Any],
    requested_by: str,
) -> Any:
    if job_runtime is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "MEMORY_WORKER_UNAVAILABLE",
                    "message": "JobRuntime not bound; cannot enqueue heavy Memory work",
                }
            },
        )
    return job_runtime.enqueue(
        capability_id=capability_id,
        arguments=arguments,
        requested_by=requested_by,
        domain="memory",
        worker_pool="memory",
        resource_class="CPU_HEAVY",
        latency_class="background",
        metadata={
            "execution_class": "EXTERNAL_REQUIRED",
            "truth": {"model_confidence_is_not_memory_truth": True},
        },
    )


def _enrich_public(record: Any) -> dict[str, Any]:
    if hasattr(record, "public_dict"):
        payload = record.public_dict()
    else:
        payload = dict(record)
    payload["source_normalized"] = normalize_source(payload.get("source"))
    payload["actor"] = actor_from_record(record)
    tags = payload.get("tags") or []
    payload["pinned"] = any(str(t).lower() == "pinned" for t in tags)
    return payload


def _default_processing() -> dict[str, Any]:
    return {
        "embeddings_enabled": True,
        "summarization_enabled": False,
        "entity_extraction_enabled": False,
        "brain_projection_enabled": True,
        "duplicate_detection_enabled": True,
    }


def _load_processing_settings(settings_service: Any | None) -> dict[str, Any]:
    base = _default_processing()
    if settings_service is None:
        # Fall back to env Settings when plane not bound.
        try:
            from Data.backend.config import get_settings

            mp = getattr(get_settings(), "memory_processing", None)
            if mp is not None:
                return {
                    "embeddings_enabled": bool(mp.embeddings_enabled),
                    "summarization_enabled": bool(mp.summarization_enabled),
                    "entity_extraction_enabled": bool(mp.entity_extraction_enabled),
                    "brain_projection_enabled": bool(mp.brain_projection_enabled),
                    "duplicate_detection_enabled": bool(mp.duplicate_detection_enabled),
                    "source": "boot_settings",
                    "persisted": False,
                }
        except Exception:  # noqa: BLE001
            pass
        return {**base, "source": "defaults", "persisted": False}

    keys = {
        "embeddings_enabled": "memory.processing.embeddings_enabled",
        "summarization_enabled": "memory.processing.summarization_enabled",
        "entity_extraction_enabled": "memory.processing.entity_extraction_enabled",
        "brain_projection_enabled": "memory.processing.brain_projection_enabled",
        "duplicate_detection_enabled": "memory.processing.duplicate_detection_enabled",
    }
    out = dict(base)
    persisted = False
    for field, key in keys.items():
        try:
            if hasattr(settings_service, "get_state"):
                state = settings_service.get_state(key)
                val = getattr(state, "effective_value", None)
                if val is None:
                    val = getattr(state, "desired_value", None)
                if val is not None:
                    out[field] = bool(val)
                if getattr(state, "source", "") == "override":
                    persisted = True
            elif hasattr(settings_service, "effective"):
                mp = getattr(settings_service.effective, "memory_processing", None)
                if mp is not None:
                    out[field] = bool(getattr(mp, field))
        except Exception:  # noqa: BLE001
            pass
    try:
        features = None
        if hasattr(settings_service, "effective"):
            features = getattr(settings_service.effective, "features", None)
        if features is not None and hasattr(features, "memory_semantic"):
            if not bool(features.memory_semantic):
                out["embeddings_enabled"] = False
    except Exception:  # noqa: BLE001
        pass
    out["source"] = "settings"
    out["persisted"] = persisted
    return out


def _topic_label(query: str) -> str | None:
    """Derive a non-sensitive topic label from short lexical tokens."""
    tokens = [t for t in query.lower().replace(",", " ").split() if len(t) >= 3][:3]
    if not tokens:
        return None
    # Drop obvious pronouns / stopwords lightly.
    stop = {"the", "and", "voor", "van", "het", "een", "met", "that", "this", "what"}
    kept = [t for t in tokens if t not in stop][:2]
    if not kept:
        return None
    return " ".join(kept)[:60]


def build_memory_router(
    *,
    memory_store: Any,
    job_runtime: Any | None = None,
    settings_service: Any | None = None,
    conversation_store: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["memory"])

    @router.get("/api/memory/overview")
    def memory_overview() -> dict:
        overview = memory_store.overview()
        processing = _load_processing_settings(settings_service)
        overview["processing"] = processing
        return {"overview": overview}

    @router.get("/api/memory/analytics")
    def memory_analytics(
        range: Annotated[str, Query()] = "7d",  # noqa: A002 — API contract
    ) -> dict:
        if range not in {"24h", "7d", "30d", "90d"}:
            raise HTTPException(status_code=422, detail="range must be 24h|7d|30d|90d")
        return {"analytics": memory_store.analytics(range_key=range)}

    @router.get("/api/memory/activity")
    def memory_activity(limit: Annotated[int, Query(ge=1, le=200)] = 40) -> dict:
        return {"activity": memory_store.list_activity(limit=limit)}

    @router.get("/api/memory/processing")
    def get_processing() -> dict:
        return {"processing": _load_processing_settings(settings_service)}

    @router.patch("/api/memory/processing")
    def patch_processing(payload: MemoryProcessingPatch) -> dict:
        if settings_service is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "SETTINGS_UNAVAILABLE",
                        "message": "Canonical Settings service not bound",
                    }
                },
            )
        mapping = {
            "embeddings_enabled": "memory.processing.embeddings_enabled",
            "summarization_enabled": "memory.processing.summarization_enabled",
            "entity_extraction_enabled": "memory.processing.entity_extraction_enabled",
            "brain_projection_enabled": "memory.processing.brain_projection_enabled",
            "duplicate_detection_enabled": "memory.processing.duplicate_detection_enabled",
        }
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            return {"processing": _load_processing_settings(settings_service)}
        patch_body = {mapping[field]: bool(updates[field]) for field in updates if field in mapping}
        try:
            if hasattr(settings_service, "patch_many"):
                settings_service.patch_many(patch_body, updated_by="api.memory.processing")
            else:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": {
                            "code": "SETTINGS_WRITE_UNSUPPORTED",
                            "message": "Settings service has no write API",
                        }
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            # SettingsError and similar
            code = getattr(exc, "code", None) or type(exc).__name__
            status = int(getattr(exc, "http_status", 500) or 500)
            raise HTTPException(
                status_code=status,
                detail=f"Failed to persist processing settings: {code}",
            ) from exc
        memory_store.record_event(
            "memory.processing_updated",
            actor="api",
            detail=updates,
        )
        return {"processing": _load_processing_settings(settings_service)}

    @router.get("/api/memory/semantic-index")
    def semantic_index_status() -> dict:
        overview = memory_store.overview()
        sem = dict(overview.get("semantic_index") or {})
        # Honest provider probe — do not claim ChromaDB.
        provider_status: dict[str, Any] = {}
        is_semantic = False
        try:
            from Data.modules.knowledge.embeddings import build_embedding_provider

            provider = build_embedding_provider(kind="auto")
            provider_status = provider.status() if hasattr(provider, "status") else {}
            is_semantic = bool(getattr(provider, "is_semantic", False) or provider_status.get("is_semantic"))
            sem["provider_id"] = sem.get("provider_id") or provider_status.get("provider_id")
            sem["model_id"] = sem.get("model_id") or provider_status.get("model_name")
            if sem.get("dimensions") is None:
                sem["dimensions"] = provider_status.get("dimensions")
            if not provider.available():
                sem["status"] = "UNAVAILABLE"
            elif not is_semantic:
                sem["status"] = "NON_SEMANTIC_PROVIDER"
            elif int(sem.get("indexed_count") or 0) <= 0:
                sem["status"] = "EMPTY"
            else:
                sem["status"] = "HEALTHY"
        except Exception as exc:  # noqa: BLE001
            sem["status"] = "UNAVAILABLE"
            provider_status = {"error": f"{type(exc).__name__}: {exc}"}
            is_semantic = False
        if sem.get("bytes") is None:
            sem["bytes_provenance"] = "UNMEASURED"
        sem["is_semantic"] = is_semantic
        sem["provider_status"] = provider_status
        sem["backend"] = "sqlite_control_memory_embeddings"
        sem["truth"] = {
            "not_chromadb_unless_configured": True,
            "hash_vectors_are_not_semantic_embeddings": not is_semantic,
        }
        return {"semantic_index": sem}

    @router.post("/api/memory/semantic-index/optimize")
    def optimize_semantic_index(response: Response) -> dict:
        """Enqueue real index maintenance — never fake green success inline for heavy work."""
        if _runners_externalized():
            job = _enqueue_memory_job(
                job_runtime,
                capability_id="memory.reconcile",
                arguments={"action": "optimize_index", "dry_run": False},
                requested_by="api.memory.semantic_index.optimize",
            )
            response.status_code = 202
            return {
                "queued": True,
                "job": job.public_dict(),
                "job_id": job.job_id,
                "truth": {"executed_via": "memory_worker", "fastapi_does_not_optimize_index": True},
            }
        # In-process path (tests / externalize off): bounded real maintenance.
        orphans = memory_store.delete_orphan_embeddings()
        targets = memory_store.list_embedding_targets(limit=50, only_missing=False)
        return {
            "queued": False,
            "orphans_removed": orphans,
            "pending_reindex": len(targets),
            "truth": {"inline_allowed_when_not_externalized": True},
        }

    @router.post("/api/memory/reindex")
    def reindex_memory(response: Response, payload: MemoryReindexRequest | None = None) -> dict:
        body = payload or MemoryReindexRequest()
        if _runners_externalized():
            job = _enqueue_memory_job(
                job_runtime,
                capability_id="memory.enrich",
                arguments={
                    "action": "index",
                    "limit": body.limit,
                    "only_missing": body.only_missing,
                },
                requested_by="api.memory.reindex",
            )
            response.status_code = 202
            return {"queued": True, "job": job.public_dict(), "job_id": job.job_id}
        # Test path: mark targets only — embedding.batch still preferred when runtime present.
        targets = memory_store.list_embedding_targets(
            limit=body.limit, only_missing=body.only_missing
        )
        return {
            "queued": False,
            "pending": [t.memory_id for t in targets],
            "count": len(targets),
        }

    @router.get("/api/memory")
    def list_memory(
        status: Annotated[str | None, Query()] = "ACTIVE",
        kind: Annotated[str | None, Query()] = None,
        source: Annotated[str | None, Query()] = None,
        trust: Annotated[str | None, Query()] = None,
        tag: Annotated[str | None, Query()] = None,
        pinned: Annotated[bool | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query()] = None,
        sort: Annotated[str, Query()] = "newest",
        conversation_id: Annotated[str | None, Query()] = None,
        project_id: Annotated[str | None, Query()] = None,
        scope: Annotated[str | None, Query()] = None,
        created_after: Annotated[str | None, Query()] = None,
        created_before: Annotated[str | None, Query()] = None,
        # Legacy unbounded clients still pass limit up to 500 via old contract —
        # clamp at route for production safety while preserving older tests that
        # construct MemoryStore.list directly.
        legacy: Annotated[bool, Query()] = False,
    ) -> dict:
        parsed_status = None
        if status:
            try:
                parsed_status = MemoryStatus(status.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid memory status: {status}") from exc
        parsed_kind = None
        if kind:
            try:
                parsed_kind = MemoryKind(kind.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid memory kind: {kind}") from exc
        parsed_scope = None
        if scope:
            try:
                parsed_scope = MemoryScope(scope.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid memory scope: {scope}") from exc
        if sort not in {"newest", "oldest", "priority", "kind", "source"}:
            raise HTTPException(status_code=422, detail="Invalid sort")
        # Prefer cursor pagination always.
        page = memory_store.list_page(
            status=parsed_status,
            kind=parsed_kind,
            source=source,
            trust=trust,
            tag=tag,
            pinned_only=bool(pinned),
            scope=parsed_scope,
            conversation_id=conversation_id,
            project_id=project_id,
            created_after=created_after,
            created_before=created_before,
            sort=sort,
            limit=min(limit, 100),
            cursor=cursor,
        )
        items = [_enrich_public(item) for item in page["memory"]]
        return {
            "memory": items,
            "next_cursor": page.get("next_cursor"),
            "limit": page.get("limit"),
            "sort": page.get("sort"),
            "pagination": {"cursor": True, "legacy": legacy},
        }

    @router.post("/api/memory")
    def create_memory(response: Response, payload: MemoryCreateRequest) -> dict:
        try:
            kind = MemoryKind(payload.kind.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid memory kind: {payload.kind}") from exc
        try:
            record = memory_store.create(
                content=payload.content,
                kind=kind,
                source=payload.source,
                trust=payload.trust,
                tags=payload.tags,
                conversation_id=payload.conversation_id,
                run_id=payload.run_id,
                scope=payload.scope,
                project_id=payload.project_id,
                workspace_id=payload.workspace_id,
                user_id=payload.user_id,
                priority=payload.priority,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        processing = _load_processing_settings(settings_service)
        queued_job = None
        if processing.get("embeddings_enabled") and _runners_externalized():
            try:
                job = _enqueue_memory_job(
                    job_runtime,
                    capability_id="memory.enrich",
                    arguments={
                        "action": "index",
                        "memory_ids": [record.memory_id],
                        "limit": 1,
                    },
                    requested_by="api.memory.create.auto_embed",
                )
                queued_job = {"job_id": job.job_id, "capability_id": "memory.enrich"}
            except HTTPException:
                # Auto-embed unavailable — memory still valid lexically.
                queued_job = {"error": "MEMORY_WORKER_UNAVAILABLE"}

        return {
            "memory": _enrich_public(record),
            "auto_embed": queued_job,
        }

    @router.get("/api/memory/search")
    def search_memory(
        q: Annotated[str, Query(min_length=1, max_length=500)],
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
        mode: Annotated[str, Query()] = "hybrid",
        conversation_id: Annotated[str | None, Query()] = None,
        project_id: Annotated[str | None, Query()] = None,
        workspace_id: Annotated[str | None, Query()] = None,
        user_id: Annotated[str | None, Query()] = None,
        scope: Annotated[str | None, Query()] = None,
        kind: Annotated[str | None, Query()] = None,
        source: Annotated[str | None, Query()] = None,
    ) -> dict:
        parsed_scope = None
        if scope:
            try:
                parsed_scope = MemoryScope(scope.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid memory scope: {scope}") from exc

        query_vector = None
        is_semantic = False
        provider_status: dict[str, Any] = {}
        mode_l = (mode or "hybrid").lower()
        if mode_l in {"semantic", "hybrid"}:
            try:
                from Data.modules.knowledge.embeddings import build_embedding_provider

                provider = build_embedding_provider(kind="auto")
                provider_status = provider.status() if hasattr(provider, "status") else {}
                is_semantic = bool(
                    getattr(provider, "is_semantic", False) or provider_status.get("is_semantic")
                )
                if provider.available() and is_semantic:
                    # Bounded single-query embed via canonical provider (same pattern as Knowledge retrieval).
                    query_vector = provider.embed_query(q)
                elif provider.available() and not is_semantic:
                    # Honest: hash vectors exist but are NOT semantic — keep lexical for "semantic" claim.
                    provider_status = {**provider_status, "note": "non_semantic_provider"}
            except Exception as exc:  # noqa: BLE001
                provider_status = {"error": f"{type(exc).__name__}: {exc}"}

        started = time.perf_counter()
        result = memory_store.search_scored(
            q,
            mode=mode_l,
            limit=limit,
            scope=parsed_scope,
            conversation_id=conversation_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            include_global=True,
            query_vector=query_vector,
            is_semantic_provider=is_semantic,
        )
        # Optional post-filters (kind/source) on bounded result set.
        items = list(result.get("memory") or [])
        if kind:
            items = [m for m in items if str(m.get("kind") or "").upper() == kind.upper()]
        if source:
            items = [m for m in items if str(m.get("source") or "").lower() == source.lower()]
        for item in items:
            item["source_normalized"] = normalize_source(item.get("source"))
            item["actor"] = actor_from_record(item)
            tags = item.get("tags") or []
            item["pinned"] = any(str(t).lower() == "pinned" for t in tags)

        duration_ms = (time.perf_counter() - started) * 1000.0
        scope_class = "scoped" if any((conversation_id, project_id, workspace_id, user_id, scope)) else "global_default"
        qhash = hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
        try:
            memory_store.record_search_telemetry(
                mode=str(result.get("mode") or mode_l),
                duration_ms=duration_ms,
                result_count=len(items),
                scope_class=scope_class,
                success=True,
                topic_label=_topic_label(q),
                query_hash=qhash,
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "memory": items,
            "mode": result.get("mode"),
            "requested_mode": mode_l,
            "degraded": result.get("degraded"),
            "degrade_reason": result.get("degrade_reason"),
            "duration_ms": round(duration_ms, 2),
            "provider_status": provider_status,
            "truth": result.get("truth")
            or {"scope_filter_required_for_retrieval": True},
        }

    @router.post("/api/memory/consolidate")
    def consolidate_memory(
        response: Response,
        payload: MemoryConsolidateRequest | None = None,
    ) -> dict:
        """Enqueue heavy Memory consolidation — never batch-inline in FastAPI when externalized."""
        body = payload or MemoryConsolidateRequest()
        if _runners_externalized():
            job = _enqueue_memory_job(
                job_runtime,
                capability_id="memory.consolidate",
                arguments={
                    "action": "consolidate",
                    "scope": body.scope,
                    "project_id": body.project_id,
                    "conversation_id": body.conversation_id,
                    "limit": body.limit,
                    "min_cluster_size": body.min_cluster_size,
                    "persist": body.persist,
                },
                requested_by="api.memory.consolidate",
            )
            response.status_code = 202
            return {
                "queued": True,
                "job": job.public_dict(),
                "job_id": job.job_id,
                "truth": {
                    "executed_via": "memory_worker",
                    "fastapi_does_not_consolidate": True,
                    "model_confidence_is_not_memory_truth": True,
                },
            }
        from Data.modules.memory import MemoryConsolidator

        episodic = memory_store.list(
            status=MemoryStatus.ACTIVE,
            kind=MemoryKind.EPISODIC,
            limit=body.limit,
            scope=MemoryScope(body.scope.upper()) if body.scope else None,
            conversation_id=body.conversation_id,
            project_id=body.project_id,
        )
        notes = memory_store.list(
            status=MemoryStatus.ACTIVE,
            kind=MemoryKind.NOTE,
            limit=body.limit,
            conversation_id=body.conversation_id,
            project_id=body.project_id,
        )
        items = [i.public_dict() for i in list(episodic) + list(notes)]
        for d in items:
            if "trust" in d and "trust_state" not in d:
                d["trust_state"] = d["trust"]
        result = MemoryConsolidator().consolidate(
            items, min_cluster_size=body.min_cluster_size
        )
        return {"queued": False, "result": result.public_dict()}

    @router.get("/api/memory/duplicates")
    def list_duplicates(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict:
        return {"duplicates": memory_store.find_exact_duplicates(limit=limit)}

    @router.post("/api/memory/from-conversation")
    def memory_from_conversation(payload: MemoryFromConversationRequest) -> dict:
        """Explicit operator action — never auto-memorize entire chats."""
        if payload.from_assistant and payload.kind.upper() == "FACT":
            raise HTTPException(
                status_code=422,
                detail="Assistant/model output cannot be stored as FACT; use NOTE/EPISODIC/SUMMARY",
            )
        try:
            kind = MemoryKind(payload.kind.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid memory kind: {payload.kind}") from exc
        trust = payload.trust
        if payload.from_assistant:
            trust = "derived"
        meta = {
            "from_conversation": True,
            "message_ids": list(payload.message_ids),
            "from_assistant": payload.from_assistant,
        }
        try:
            record = memory_store.create(
                content=payload.content,
                kind=kind,
                source="conversation",
                trust=trust,
                tags=list(payload.tags) + (["from_conversation"]),
                conversation_id=payload.conversation_id,
                scope=MemoryScope.CONVERSATION,
                metadata=meta,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"memory": _enrich_public(record)}

    @router.get("/api/memory/{memory_id}")
    def get_memory(memory_id: str) -> dict:
        item = memory_store.get(memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        payload = _enrich_public(item)
        emb = None
        try:
            emb = memory_store.get_embedding(memory_id)
            if emb:
                emb = {k: v for k, v in emb.items() if k != "vector"}
                emb["has_vector"] = True
        except Exception:  # noqa: BLE001
            emb = None
        payload["semantic_index"] = emb
        return {"memory": payload}

    @router.patch("/api/memory/{memory_id}")
    def patch_memory(memory_id: str, payload: MemoryPatchRequest) -> dict:
        try:
            item = memory_store.update(
                memory_id,
                tags=payload.tags,
                priority=payload.priority,
                valid_until=payload.valid_until,
                clear_valid_until=payload.clear_valid_until,
                metadata_patch=payload.metadata_patch,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": _enrich_public(item)}

    @router.post("/api/memory/{memory_id}/pin")
    def pin_memory(memory_id: str) -> dict:
        item = memory_store.pin(memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": _enrich_public(item)}

    @router.post("/api/memory/{memory_id}/unpin")
    def unpin_memory(memory_id: str) -> dict:
        item = memory_store.unpin(memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": _enrich_public(item)}

    @router.post("/api/memory/{memory_id}/correct")
    def correct_memory(memory_id: str, payload: MemoryCorrectRequest) -> dict:
        kind = None
        if payload.kind:
            try:
                kind = MemoryKind(payload.kind.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid memory kind: {payload.kind}") from exc
        try:
            item = memory_store.correct(
                memory_id,
                content=payload.content,
                kind=kind,
                trust=payload.trust,
                tags=payload.tags,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Memory not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"memory": _enrich_public(item)}

    @router.post("/api/memory/{memory_id}/archive")
    def archive_memory(memory_id: str) -> dict:
        item = memory_store.set_status(memory_id, MemoryStatus.ARCHIVED)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": _enrich_public(item)}

    @router.post("/api/memory/{memory_id}/restore")
    def restore_memory(memory_id: str) -> dict:
        try:
            item = memory_store.restore(memory_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": _enrich_public(item)}

    @router.post("/api/memory/{memory_id}/revoke")
    def revoke_memory(memory_id: str) -> dict:
        item = memory_store.set_status(memory_id, MemoryStatus.REVOKED)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": _enrich_public(item)}

    return router
