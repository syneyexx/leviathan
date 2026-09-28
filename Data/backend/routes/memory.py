"""Durable memory HTTP routes."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from Data.modules.memory import MemoryKind, MemoryScope, MemoryStatus


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


class MemoryConsolidateRequest(BaseModel):
    scope: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)
    min_cluster_size: int = Field(default=2, ge=2, le=50)
    persist: bool = True


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


def build_memory_router(*, memory_store: Any, job_runtime: Any | None = None) -> APIRouter:
    router = APIRouter(tags=["memory"])

    @router.get("/api/memory")
    def list_memory(
        status: Annotated[str | None, Query()] = "ACTIVE",
        kind: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        conversation_id: Annotated[str | None, Query()] = None,
        project_id: Annotated[str | None, Query()] = None,
        scope: Annotated[str | None, Query()] = None,
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
        items = memory_store.list(
            status=parsed_status,
            kind=parsed_kind,
            limit=limit,
            scope=parsed_scope,
            conversation_id=conversation_id,
            project_id=project_id,
        )
        return {"memory": [item.public_dict() for item in items]}

    @router.post("/api/memory")
    def create_memory(payload: MemoryCreateRequest) -> dict:
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
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"memory": record.public_dict()}

    @router.get("/api/memory/search")
    def search_memory(
        q: Annotated[str, Query(min_length=1, max_length=500)],
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
        conversation_id: Annotated[str | None, Query()] = None,
        project_id: Annotated[str | None, Query()] = None,
    ) -> dict:
        items = memory_store.search(
            q,
            limit=limit,
            conversation_id=conversation_id,
            project_id=project_id,
            include_global=True,
        )
        return {
            "memory": [item.public_dict() for item in items],
            "truth": {"scope_filter_required_for_retrieval": True},
        }

    @router.post("/api/memory/consolidate")
    def consolidate_memory(
        response: Response,
        payload: MemoryConsolidateRequest | None = None,
    ) -> dict:
        """Enqueue heavy Memory consolidation — never batch-inline in FastAPI when externalized."""
        body = payload or MemoryConsolidateRequest()
        if _runners_externalized():
            if job_runtime is None:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": {
                            "code": "MEMORY_WORKER_UNAVAILABLE",
                            "message": "JobRuntime not bound; cannot enqueue memory.consolidate",
                        }
                    },
                )
            job = job_runtime.enqueue(
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
                domain="memory",
                worker_pool="memory",
                resource_class="CPU_HEAVY",
                latency_class="background",
                metadata={
                    "execution_class": "EXTERNAL_REQUIRED",
                    "truth": {"model_confidence_is_not_memory_truth": True},
                },
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
        # Test / legacy in-process path when externalize is off.
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

    @router.get("/api/memory/{memory_id}")
    def get_memory(memory_id: str) -> dict:
        item = memory_store.get(memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": item.public_dict()}

    @router.post("/api/memory/{memory_id}/archive")
    def archive_memory(memory_id: str) -> dict:
        item = memory_store.set_status(memory_id, MemoryStatus.ARCHIVED)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": item.public_dict()}

    @router.post("/api/memory/{memory_id}/revoke")
    def revoke_memory(memory_id: str) -> dict:
        item = memory_store.set_status(memory_id, MemoryStatus.REVOKED)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"memory": item.public_dict()}

    return router
