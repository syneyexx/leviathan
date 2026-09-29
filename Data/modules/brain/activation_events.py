"""Emit public brain.knowledge_activation events for Chat → Brain sync.

Maps retrieval hit document/memory ids onto Brain facade node ids.
Never invents node ids from keyword matching.
"""

from __future__ import annotations

from typing import Any


def brain_node_ids_from_hits(
    *,
    knowledge_hits: list[dict[str, Any]] | None = None,
    memory_hits: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Convert retrieval hits to Brain graph node ids (stable prefixes)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in knowledge_hits or []:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("id") or item.get("document_id")
        if not doc_id:
            continue
        nid = f"knowledge:document:{doc_id}"
        if nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    for item in memory_hits or []:
        if not isinstance(item, dict):
            continue
        mid = item.get("memory_id") or item.get("id")
        if not mid:
            continue
        nid = f"memory:{mid}"
        if nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def emit_knowledge_activation(
    observability: Any,
    *,
    conversation_id: str | None,
    request_id: str | None,
    run_id: str | None,
    phase: str,
    knowledge_hits: list[dict[str, Any]] | None = None,
    memory_hits: list[dict[str, Any]] | None = None,
    hit_count: int | None = None,
    identifiers_available: bool | None = None,
) -> Any:
    """Publish a typed activation event on the shared observability hub."""
    node_ids = brain_node_ids_from_hits(
        knowledge_hits=knowledge_hits,
        memory_hits=memory_hits,
    )
    if identifiers_available is None:
        identifiers_available = bool(node_ids)
    if not identifiers_available:
        node_ids = []
    count = hit_count if hit_count is not None else (
        len(knowledge_hits or []) + len(memory_hits or [])
    )
    payload = {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "run_id": run_id,
        "phase": phase,
        "hit_count": count,
        "node_ids": node_ids,
        "identifiers_available": bool(identifiers_available and node_ids),
        "truth": {
            "node_ids_are_retrieval_backed": bool(node_ids),
            "hit_count_alone_is_not_identity": True,
            "no_keyword_activation": True,
        },
    }
    return observability.emit(
        "brain",
        "knowledge_activation",
        level="info",
        message="brain.knowledge_activation",
        request_id=request_id,
        correlation_id=conversation_id,
        run_id=run_id,
        payload=payload,
    )
