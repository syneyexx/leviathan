"""Canonical Memory source normalization — presentation/analytics only.

Does NOT mutate original provenance strings on MemoryRecord.source.
"""

from __future__ import annotations

from typing import Any


# Normalized categories used by UI filters / Top Sources / KPIs.
SOURCE_CATEGORIES: tuple[str, ...] = (
    "manual",
    "conversation",
    "agent",
    "research",
    "consolidation",
    "imported",
    "browser",
    "correction",
    "system",
    "other",
)


_MAP: dict[str, str] = {
    "manual": "manual",
    "user": "manual",
    "ui": "manual",
    "operator": "manual",
    "conversation": "conversation",
    "chat": "conversation",
    "message": "conversation",
    "agent": "agent",
    "assistant": "agent",
    "orchestrator": "agent",
    "signal": "agent",
    "research": "research",
    "web_research": "research",
    "web": "research",
    "consolidation": "consolidation",
    "derived": "consolidation",
    "imported": "imported",
    "import": "imported",
    "snapshot_restore": "imported",
    "browser": "browser",
    "browser_derived": "browser",
    "correction": "correction",
    "system": "system",
    "memory_worker": "system",
    "reconcile": "system",
}


def normalize_source(source: str | None) -> str:
    """Map a raw provenance string to a stable presentation category."""
    raw = (source or "").strip().lower()
    if not raw:
        return "other"
    if raw in _MAP:
        return _MAP[raw]
    for key, cat in _MAP.items():
        if key in raw:
            return cat
    return "other"


def actor_from_record(record: Any) -> str | None:
    """Derive proven actor/agent label or None (UI shows —)."""
    meta = {}
    if hasattr(record, "metadata"):
        meta = dict(getattr(record, "metadata") or {})
    elif isinstance(record, dict):
        meta = dict(record.get("metadata") or {})

    for key in ("agent_id", "agent_name", "actor", "sender_id", "sender"):
        val = meta.get(key)
        if val:
            return str(val)[:80]

    source = ""
    if hasattr(record, "source"):
        source = str(getattr(record, "source") or "")
    elif isinstance(record, dict):
        source = str(record.get("source") or "")
    cat = normalize_source(source)
    if cat == "agent" and source:
        return source[:80]
    if cat == "system":
        return "System"
    if cat == "consolidation":
        return "Memory Worker"
    if cat == "research":
        return "Research"
    if cat == "conversation":
        return "Conversation"
    return None
