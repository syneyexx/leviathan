"""Temporal Intelligence Graph — valid-time / observed-time belief queries.

Edges carry valid_from/valid_until (valid time) and observed_at (knowledge time).
``as_of_beliefs`` never uses future observations when ``known_as_of`` is set.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from gen2.store import Gen2Store

RecordFn = Callable[..., dict[str, Any]]

ALLOWED_RELATION_KINDS = frozenset(
    {
        "related_to",
        "supports",
        "derived_from",
        "supersedes",
        "contradicts",
        "caused_by",
        "affected_by",
        "mentions",
        "produced_by",
        "asserts",
    }
)


def assert_edge(
    store: Gen2Store,
    record: RecordFn,
    values: dict[str, Any],
    *,
    require_provenance: bool = False,
) -> dict[str, Any]:
    required = ("source_id", "target_id")
    for key in required:
        if not values.get(key):
            raise ValueError(f"{key} required")
    payload = dict(values)
    relation_kind = str(payload.get("relation_kind") or payload.get("relation") or "related_to").strip()
    if relation_kind not in ALLOWED_RELATION_KINDS:
        # Preserve unknown kinds as metadata but keep a typed primary relation.
        payload.setdefault("metadata", {})
        if isinstance(payload["metadata"], dict):
            payload["metadata"] = {**payload["metadata"], "original_relation_kind": relation_kind}
        relation_kind = "related_to"
    payload["relation_kind"] = relation_kind
    payload["relation"] = str(payload.get("relation") or relation_kind)
    if require_provenance:
        provenance = str(payload.get("provenance") or "").strip()
        if not provenance:
            raise ValueError("provenance required")
        if payload.get("confidence") is None:
            raise ValueError("confidence required")
        try:
            conf = float(payload["confidence"])
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a float") from exc
        if conf < 0 or conf > 1:
            raise ValueError("confidence must be between 0 and 1")
        payload["confidence"] = conf
        payload["provenance"] = provenance
    edge = store.add_graph_edge(payload)
    record(edge["id"], "ARTIFACT_CREATED", {"kind": "graph_edge"}, component="temporal_graph")
    return edge


def as_of_beliefs(
    store: Gen2Store,
    entity_id: str,
    as_of: str,
    *,
    known_as_of: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Beliefs about entity valid at ``as_of`` (valid-time).

    ``known_as_of`` (default: same as ``as_of``) filters observed_at so historical
    analysis cannot use future knowledge.
    """
    observed_cut = known_as_of if known_as_of is not None else as_of
    related = store.list_graph_edges(
        entity_id=entity_id,
        as_of=as_of,
        known_as_of=observed_cut,
        limit=limit,
    )
    superseded = [e for e in related if e.get("supersedes")]
    contradictions = [e for e in related if e.get("relation_kind") == "contradicts" or e.get("contradicts")]
    return {
        "entity_id": entity_id,
        "as_of": as_of,
        "known_as_of": observed_cut,
        "valid_time": as_of,
        "observed_time_cutoff": observed_cut,
        "beliefs": related,
        "superseded_links": superseded,
        "contradictions": contradictions,
        "count": len(related),
        "ok": len(related) > 0,
        "error": None if related else "no_beliefs",
        "queryable": True,
        "bitemporal": True,
        "note": "Valid-time + observed-time filters; not a full graph database engine.",
    }


def find_contradictions(store: Gen2Store, entity_id: str | None = None) -> list[dict[str, Any]]:
    edges = store.list_graph_edges(source_id=entity_id, limit=500) if entity_id else store.list_graph_edges(limit=500)
    out = []
    for edge in edges:
        if edge.get("relation_kind") == "contradicts" or edge.get("contradicts"):
            out.append(edge)
    return out


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", text or "")}


def find_analogues(
    store: Gen2Store,
    *,
    entity_id: str | None = None,
    relation_kind: str | None = None,
    text: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find similar situations by shared entities / relation kinds / token overlap.

    Offline local search over persisted edges — not an embedding service.
    """
    edges = store.list_graph_edges(limit=5000)
    if entity_id:
        edges = [
            e
            for e in edges
            if entity_id in {e.get("source_id"), e.get("target_id")}
            or entity_id in str(e.get("provenance") or "")
        ]
    if relation_kind:
        edges = [e for e in edges if e.get("relation_kind") == relation_kind or e.get("relation") == relation_kind]

    query_tokens = _tokenize(text or "")
    scored: list[dict[str, Any]] = []
    for edge in edges:
        blob = " ".join(
            [
                str(edge.get("source_id") or ""),
                str(edge.get("target_id") or ""),
                str(edge.get("relation_kind") or ""),
                str(edge.get("provenance") or ""),
                str(edge.get("source_ref") or ""),
            ]
        )
        tokens = _tokenize(blob)
        overlap = query_tokens & tokens if query_tokens else set()
        score = float(len(overlap)) + float(edge.get("confidence") or 0) * 0.1
        if not query_tokens:
            score = float(edge.get("confidence") or 0.5)
        if query_tokens and not overlap:
            continue
        scored.append(
            {
                "edge": edge,
                "score": round(score, 4),
                "overlap_tokens": sorted(overlap)[:12],
                "method": "token_overlap_local",
            }
        )
    scored.sort(key=lambda row: (-float(row["score"]), str((row["edge"] or {}).get("id") or "")))
    return {
        "entity_id": entity_id,
        "relation_kind": relation_kind,
        "query_text": text,
        "analogues": scored[: max(1, min(int(limit), 100))],
        "count": min(len(scored), max(1, min(int(limit), 100))),
        "method": "token_overlap_local",
        "note": "Local analogue search over graph edges; not vector similarity.",
    }


def cross_store_link_plan(
    *,
    memory_ids: list[str] | None = None,
    knowledge_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    research_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Describe typed cross-store links without mixing Memory/Knowledge/Evidence roles."""
    links: list[dict[str, Any]] = []
    for mid in memory_ids or []:
        links.append({"from": f"memory:{mid}", "relation_kind": "derived_from", "role": "memory"})
    for kid in knowledge_ids or []:
        links.append({"from": f"knowledge:{kid}", "relation_kind": "supports", "role": "knowledge"})
    for eid in evidence_ids or []:
        links.append({"from": f"evidence:{eid}", "relation_kind": "supports", "role": "evidence"})
    for rid in research_ids or []:
        links.append({"from": f"research:{rid}", "relation_kind": "derived_from", "role": "research"})
    return {
        "links": links,
        "roles_preserved": True,
        "note": "Link plan only — callers must persist edges with provenance; roles stay distinct (D004).",
    }
