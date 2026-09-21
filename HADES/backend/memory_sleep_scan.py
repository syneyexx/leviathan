"""Idle/manual scan of recent conversations → memory proposal candidates (Wave 24)."""
from __future__ import annotations

from typing import Any


def scan_memory_candidates(database: Any, *, limit_conversations: int = 8, limit_messages: int = 12) -> list[dict[str, Any]]:
    """Create pending memory proposals from recent user statements. Never auto-writes durable memory."""
    created: list[dict[str, Any]] = []
    conversations = database.list_conversations()[: max(1, int(limit_conversations))]
    for conv in conversations:
        cid = str(conv.get("id") or "")
        if not cid:
            continue
        messages = database.list_messages(cid)[-max(1, int(limit_messages)) :]
        for msg in messages:
            if str(msg.get("role") or "") != "user":
                continue
            content = str(msg.get("content") or "").strip()
            if len(content) < 40 or content.startswith("/"):
                continue
            # Lightweight heuristic: preference / fact-like sentences.
            lower = content.lower()
            if not any(token in lower for token in ("ik wil", "i prefer", "onthoud", "remember", "altijd", "never", "voorkeur")):
                continue
            title = (content[:72] + "…") if len(content) > 72 else content
            proposal = database.create_memory_proposal(
                {
                    "title": title,
                    "content": content,
                    "summary": title,
                    "origin_kind": "sleep_time_scan",
                    "source_conversation_id": cid,
                    "source_message_id": msg.get("id"),
                }
            )
            created.append(proposal)
            if len(created) >= 20:
                return created
    return created
