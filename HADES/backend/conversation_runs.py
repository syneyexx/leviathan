"""Conversation ↔ run binding for Chat timeline reconnect (HADES-10 Phase 3A).

Persists links between a conversation and existing engines (tool/coding/research/
work/approval/artifact/verification) without inventing a second orchestrator.
Reuse run_event_bus / gen2_run_events for event payloads; this table only stores
identity + status for reconnect after refresh.
"""

from __future__ import annotations

from typing import Any, Literal

from platform_db import new_id, utc_now

ConversationRunType = Literal[
    "tool",
    "coding",
    "research",
    "work",
    "approval",
    "artifact",
    "verification",
    "chat",
]

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "rejected", "expired"})


def bind_conversation_run(
    platform_db: Any,
    *,
    conversation_id: str,
    run_id: str,
    run_type: str,
    status: str = "running",
    title: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent upsert of a conversation↔run link."""
    return platform_db.upsert_conversation_run(
        conversation_id=conversation_id,
        run_id=run_id,
        run_type=run_type,
        status=status,
        title=title,
        metadata=metadata or {},
    )


def list_conversation_runs(
    platform_db: Any,
    conversation_id: str,
    *,
    active_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = platform_db.list_conversation_runs(conversation_id, limit=limit)
    if not active_only:
        return rows
    return [row for row in rows if str(row.get("status") or "") not in TERMINAL_STATUSES]


def update_conversation_run_status(
    platform_db: Any,
    *,
    conversation_id: str,
    run_id: str,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return platform_db.update_conversation_run_status(
        conversation_id=conversation_id,
        run_id=run_id,
        status=status,
        metadata=metadata,
    )


def new_conversation_run_id(prefix: str = "crun") -> str:
    return new_id(prefix)


def stamp_now() -> str:
    return utc_now()
