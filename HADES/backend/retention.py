"""Bounded retention for unbounded event/log tables (F-15 / T8).

Uses ``logging.retention_days`` / legacy ``log_retention_days`` when present.
``0`` or unset with ``allow_unlimited`` semantics: skip prune (no silent wipe).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def resolve_retention_days(settings: dict[str, Any] | None) -> int | None:
    """Return positive retention days, or None when pruning is disabled."""
    cfg = settings if isinstance(settings, dict) else {}
    raw = cfg.get("logging.retention_days", cfg.get("log_retention_days"))
    if raw is None:
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return days


def cutoff_iso(days: int, *, now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    return (stamp - timedelta(days=int(days))).isoformat(timespec="seconds")


def prune_platform_tables(
    platform_db: Any,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete aged research_events, agent_usage_events, and finished tool_calls."""
    cutoff = cutoff_iso(retention_days, now=now)
    deleted: dict[str, int] = {
        "research_events": 0,
        "agent_usage_events": 0,
        "tool_calls": 0,
    }
    with platform_db.connection() as db:
        cur = db.execute("DELETE FROM research_events WHERE created_at < ?", (cutoff,))
        deleted["research_events"] = int(cur.rowcount or 0)
        cur = db.execute("DELETE FROM agent_usage_events WHERE created_at < ?", (cutoff,))
        deleted["agent_usage_events"] = int(cur.rowcount or 0)
        # Keep in-flight tool calls; only prune finished rows.
        cur = db.execute(
            """DELETE FROM tool_calls
               WHERE (finished_at IS NOT NULL AND finished_at < ?)
                  OR (finished_at IS NULL AND started_at < ?
                      AND status IN ('completed','failed','blocked','cancelled','interrupted'))""",
            (cutoff, cutoff),
        )
        deleted["tool_calls"] = int(cur.rowcount or 0)
    return deleted


def prune_core_tables(
    database: Any,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete aged messages and task_events (conversations/tasks rows remain)."""
    cutoff = cutoff_iso(retention_days, now=now)
    deleted: dict[str, int] = {"messages": 0, "task_events": 0}
    with database.connection() as db:
        cur = db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        deleted["messages"] = int(cur.rowcount or 0)
        cur = db.execute("DELETE FROM task_events WHERE created_at < ?", (cutoff,))
        deleted["task_events"] = int(cur.rowcount or 0)
    return deleted


def run_retention_job(
    *,
    database: Any,
    platform_db: Any,
    settings: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prune unbounded tables when retention_days is configured and positive."""
    days = resolve_retention_days(settings)
    if days is None:
        return {"ok": True, "skipped": True, "reason": "retention_disabled_or_unset", "deleted": {}}
    core = prune_core_tables(database, retention_days=days, now=now)
    platform = prune_platform_tables(platform_db, retention_days=days, now=now)
    return {
        "ok": True,
        "skipped": False,
        "retention_days": days,
        "cutoff": cutoff_iso(days, now=now),
        "deleted": {**core, **platform},
    }
