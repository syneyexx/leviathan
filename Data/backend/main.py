from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import FRONTEND_ROOT, settings
from .database import Database
from .llm import LLMUnavailable, OpenAICompatibleLLM
from .reasoning import ReasoningEngine


db = Database(settings.database_path)
reasoner = ReasoningEngine()
llm = OpenAICompatibleLLM(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    yield


app = FastAPI(title="Leviathan", version="0.1.0-step1", lifespan=lifespan)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    conversation_id: str | None = None


class KnowledgeWrite(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=250_000)
    source: str = Field(default="manual", min_length=1, max_length=240)


@app.get("/api/health")
async def health() -> dict:
    model = await llm.health()
    return {
        "ok": True,
        "version": app.version,
        "database": str(settings.database_path),
        "reasoning_enabled": settings.reasoning_enabled,
        "llm": model,
    }


@app.get("/api/conversations")
def list_conversations() -> dict:
    return {"conversations": db.list_conversations()}


@app.post("/api/conversations")
def create_conversation(payload: ConversationCreate) -> dict:
    return {"conversation": db.create_conversation(payload.title.strip())}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    conversation = db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation": conversation,
        "messages": db.get_messages(conversation_id, limit=200),
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    if payload.conversation_id:
        conversation = db.get_conversation(payload.conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = db.create_conversation()

    conversation_id = conversation["id"]
    user_message = db.add_message(conversation_id, "user", message)

    if conversation["title"] == "New conversation":
        title = " ".join(message.split())[:72] or "New conversation"
        db.set_conversation_title(conversation_id, title)

    has_knowledge = bool(db.list_knowledge(limit=1))
    plan = reasoner.analyze(message, has_knowledge) if settings.reasoning_enabled else ReasoningEngine().analyze(message, False)
    knowledge = db.search_knowledge(message, settings.knowledge_top_k) if plan.use_knowledge else []

    history_rows = db.get_messages(conversation_id, limit=settings.max_history_messages)
    history = [{"role": row["role"], "content": row["content"]} for row in history_rows]

    try:
        answer, model = await llm.chat(history=history, knowledge=knowledge, plan=plan)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    assistant_message = db.add_message(conversation_id, "assistant", answer)
    return {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "model": model,
        "reasoning": plan.public_summary(),
        "knowledge_sources": [
            {"id": item["id"], "title": item["title"], "source": item["source"]}
            for item in knowledge
        ],
    }


@app.get("/api/knowledge")
def list_knowledge() -> dict:
    return {"documents": db.list_knowledge()}


@app.post("/api/knowledge")
def write_knowledge(payload: KnowledgeWrite) -> dict:
    document = db.upsert_knowledge(
        document_id=payload.id,
        title=payload.title.strip(),
        content=payload.content.strip(),
        source=payload.source.strip(),
    )
    return {"document": document}


@app.get("/api/knowledge/search")
def search_knowledge(q: Annotated[str, Query(min_length=1, max_length=4000)], limit: int = 5) -> dict:
    safe_limit = min(max(limit, 1), 20)
    return {"documents": db.search_knowledge(q, safe_limit)}


@app.delete("/api/knowledge/{document_id}")
def delete_knowledge(document_id: str) -> dict:
    if not db.delete_knowledge(document_id):
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"deleted": True, "id": document_id}


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(FRONTEND_ROOT / "index.html")


@app.get("/chat.html")
def chat_page() -> FileResponse:
    return FileResponse(FRONTEND_ROOT / "chat.html")


for route, folder in (("/assets", "assets"), ("/css", "css"), ("/js", "js")):
    app.mount(route, StaticFiles(directory=FRONTEND_ROOT / folder), name=folder)
