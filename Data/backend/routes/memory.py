"""Durable memory HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
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


def build_memory_router(*, memory_store: Any) -> APIRouter:
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
