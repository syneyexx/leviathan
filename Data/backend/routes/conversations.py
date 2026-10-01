"""Conversation CRUD HTTP routes — cursor pagination + message pages + turn hydration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None


def build_conversations_router(*, db: Any, chat_turn_store: Any | None = None) -> APIRouter:
    router = APIRouter(tags=["conversations"])

    @router.get("/api/conversations")
    def list_conversations(
        q: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict:
        try:
            page = db.list_conversations_page(limit=limit, q=q, cursor=cursor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "conversations": page["items"],
            "items": page["items"],
            "next_cursor": page.get("next_cursor"),
            "has_more": page.get("has_more", False),
            "total": page.get("total"),
        }

    @router.post("/api/conversations")
    def create_conversation(payload: ConversationCreate) -> dict:
        return {"conversation": db.create_conversation(payload.title.strip())}

    @router.get("/api/conversations/{conversation_id}")
    def get_conversation(
        conversation_id: str,
        limit: int = Query(100, ge=1, le=500),
        before_id: int | None = Query(None, ge=1),
        after_id: int | None = Query(None, ge=1),
        include_turns: bool = Query(True),
    ) -> dict:
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if before_id is not None and after_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Specify at most one of before_id or after_id",
            )
        page = db.get_messages_page(
            conversation_id,
            limit=limit,
            before_id=before_id,
            after_id=after_id,
        )
        messages = page["items"]
        turns_by_message: dict[str, Any] = {}
        if include_turns and chat_turn_store is not None:
            assistant_ids = [
                int(m["id"]) for m in messages if m.get("role") == "assistant" and m.get("id") is not None
            ]
            found = chat_turn_store.list_by_message_ids(assistant_ids)
            turns_by_message = {str(mid): turn.public_dict() for mid, turn in found.items()}
        return {
            "conversation": conversation,
            "messages": messages,
            "has_more": page.get("has_more", False),
            "next_before_id": page.get("next_before_id"),
            "next_after_id": page.get("next_after_id"),
            "message_count": db.count_messages(conversation_id),
            "turns": turns_by_message,
        }

    @router.get("/api/conversations/{conversation_id}/messages")
    def list_messages(
        conversation_id: str,
        limit: int = Query(100, ge=1, le=500),
        before_id: int | None = Query(None, ge=1),
        after_id: int | None = Query(None, ge=1),
        include_turns: bool = Query(True),
    ) -> dict:
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if before_id is not None and after_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Specify at most one of before_id or after_id",
            )
        page = db.get_messages_page(
            conversation_id,
            limit=limit,
            before_id=before_id,
            after_id=after_id,
        )
        messages = page["items"]
        turns_by_message: dict[str, Any] = {}
        if include_turns and chat_turn_store is not None:
            assistant_ids = [
                int(m["id"]) for m in messages if m.get("role") == "assistant" and m.get("id") is not None
            ]
            found = chat_turn_store.list_by_message_ids(assistant_ids)
            turns_by_message = {str(mid): turn.public_dict() for mid, turn in found.items()}
        return {
            "messages": messages,
            "has_more": page.get("has_more", False),
            "next_before_id": page.get("next_before_id"),
            "next_after_id": page.get("next_after_id"),
            "turns": turns_by_message,
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
