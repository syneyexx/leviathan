"""Multimodal session HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.context import (
    ContextBuilder,
    MultimodalPart,
    PartKind,
    new_sync_id,
)


class MultimodalSessionCreate(BaseModel):
    conversation_id: str | None = None
    run_id: str | None = None
    project_id: str | None = None


class MultimodalPartIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    text: str | None = None
    mime_type: str | None = None
    artifact_id: str | None = None
    uri: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: float | None = None
    region: dict | None = None
    timespan: dict | None = None
    provenance: dict | None = None
    scope: str = "conversation"


class MultimodalAppendRequest(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    parts: list[MultimodalPartIn] = Field(min_length=1)
    sync_id: str | None = None


def _part_from_payload(item: MultimodalPartIn) -> MultimodalPart:
    kind = item.kind.lower()
    if kind == PartKind.TEXT.value:
        return MultimodalPart.text_part(item.text or "", scope=item.scope)
    if kind in {PartKind.IMAGE.value, PartKind.REGION.value}:
        return MultimodalPart.image_part(
            mime_type=item.mime_type or "image/png",
            artifact_id=item.artifact_id,
            uri=item.uri,
            width=item.width,
            height=item.height,
            region=item.region,
            provenance=item.provenance,
            scope=item.scope,
        )
    if kind in {PartKind.AUDIO.value, PartKind.TIMESPAN.value}:
        return MultimodalPart.audio_part(
            mime_type=item.mime_type or "audio/wav",
            artifact_id=item.artifact_id,
            duration_ms=item.duration_ms,
            timespan=item.timespan,
            text=item.text,
            provenance=item.provenance,
            scope=item.scope,
        )
    try:
        part_kind = PartKind(kind)
    except ValueError:
        part_kind = PartKind.FILE
    return MultimodalPart(
        part_id=f"part_{new_sync_id().replace('sync_', '')[:10]}",
        kind=part_kind,
        mime_type=item.mime_type or "application/octet-stream",
        text=item.text,
        artifact_id=item.artifact_id,
        uri=item.uri,
        width=item.width,
        height=item.height,
        duration_ms=item.duration_ms,
        region=item.region,
        timespan=item.timespan,
        provenance=dict(item.provenance or {}),
        scope=item.scope,
    )


def build_multimodal_router(
    *,
    settings: Any,
    multimodal_sessions: Any,
    reasoner: Any,
) -> APIRouter:
    router = APIRouter(tags=["multimodal"])

    @router.post("/api/multimodal/sessions")
    def create_multimodal_session(payload: MultimodalSessionCreate) -> dict:
        if not settings.features.multimodal_realtime:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_MULTIMODAL_REALTIME=false"})
        session = multimodal_sessions.create(
            conversation_id=payload.conversation_id,
            run_id=payload.run_id,
            project_id=payload.project_id,
        )
        return {"session": session.public_dict()}

    @router.get("/api/multimodal/sessions/{session_id}")
    def get_multimodal_session(session_id: str) -> dict:
        session = multimodal_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="multimodal session not found")
        return {"session": session.public_dict()}

    @router.post("/api/multimodal/sessions/{session_id}/messages")
    def append_multimodal_message(session_id: str, payload: MultimodalAppendRequest) -> dict:
        if not settings.features.multimodal_realtime:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_MULTIMODAL_REALTIME=false"})
        try:
            session = multimodal_sessions.require(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        parts = [_part_from_payload(p) for p in payload.parts]
        message = session.append(payload.role, parts, sync_id=payload.sync_id)
        return {"message": message.public_dict(), "session": session.public_dict()}

    @router.post("/api/multimodal/sessions/{session_id}/context")
    def multimodal_session_context(session_id: str) -> dict:
        """Compile ContextPack from fused multimodal history (exit-gate surface)."""
        session = multimodal_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="multimodal session not found")
        history = session.history_for_context()
        plan = reasoner.analyze(
            history[-1]["content"] if history else "multimodal",
            has_knowledge=False,
        )
        pack = ContextBuilder(
            token_budget=settings.context.token_budget,
            max_knowledge_chars=settings.context.max_knowledge_chars,
            max_history_messages=settings.resources.max_history_messages,
            reserve_response_tokens=settings.context.reserve_response_tokens,
        ).build(history=history, knowledge=[], plan=plan)
        return {
            "session_id": session_id,
            "pack": pack.public_dict(),
            "truth": {
                "single_context_run_history": True,
                "same_conversation_project_context_model": True,
            },
        }

    return router
