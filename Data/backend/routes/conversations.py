"""Conversation CRUD HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None


def build_conversations_router(*, db: Any) -> APIRouter:
    router = APIRouter(tags=["conversations"])

    @router.get("/api/conversations")
    def list_conversations(q: str | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
        return {"conversations": db.list_conversations(limit=limit, q=q)}

    @router.post("/api/conversations")
    def create_conversation(payload: ConversationCreate) -> dict:
        return {"conversation": db.create_conversation(payload.title.strip())}

    @router.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict:
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {
            "conversation": conversation,
            "messages": db.get_messages(conversation_id, limit=200),
        }

    @router.patch("/api/conversations/{conversation_id}")
    def update_conversation(conversation_id: str, payload: ConversationUpdate) -> dict:
        if payload.title is None and payload.pinned is None:
            raise HTTPException(status_code=422, detail="No conversation fields to update")
        conversation = db.update_conversation(
            conversation_id,
            title=payload.title.strip() if payload.title is not None else None,
            pinned=payload.pinned,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"conversation": conversation}

    @router.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str) -> dict:
        if not db.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"deleted": True, "id": conversation_id}

    return router
