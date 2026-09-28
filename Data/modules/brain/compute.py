"""Heavy DERIVED Brain computation — never a Brain database.

brain_compute produces advisory snapshots/metrics/proposals from authoritative
stores. Canonical mutations remain with Knowledge / Memory / Research owners.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


ALGORITHM_VERSION = "brain_derived_v1"


def _fail(
    store: Any,
    job: Any,
    error: str,
    *,
    metadata: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    try:
        fenced_transition(
            store,
            job.job_id,
            JobState.FAILED,
            worker_id=worker_id,
            ctx=ctx,
            error=error,
            metadata_update=metadata or {},
        )
    except Exception:  # noqa: BLE001
        pass
    return {"error": error}


def _complete(
    store: Any,
    job: Any,
    result: dict[str, Any],
    *,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from Data.modules.jobs.leases import fenced_transition
    from Data.modules.jobs.states import JobState

    worker_id = str((ctx or {}).get("worker_id") or getattr(job, "lease_owner", None) or "")
    fenced_transition(
        store,
        job.job_id,
        JobState.COMPLETED,
        worker_id=worker_id,
        ctx=ctx,
        result=result,
    )
    return result


def _build_facade(ctx: dict[str, Any]) -> Any:
    bound = ctx.get("brain_facade")
    if bound is not None:
        return bound
    # Prefer explicit list callbacks from worker context when provided.
    from Data.modules.brain import BrainQueryFacade

    facade = BrainQueryFacade(
        knowledge_list=ctx.get("knowledge_list"),
        evidence_list=ctx.get("evidence_list"),
        research_list=ctx.get("research_list"),
        dataset_list=ctx.get("dataset_list"),
        memory_list=ctx.get("memory_list"),
        module_list=ctx.get("module_list"),
        capability_list=ctx.get("capability_list"),
        relation_list=ctx.get("relation_list"),
        max_nodes=min(int(ctx.get("brain_max_nodes") or 1000), 1000),
        max_edges=min(int(ctx.get("brain_max_edges") or 2000), 2000),
    )
    ctx["brain_facade"] = facade
    return facade


def _community_components(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic connected-component clustering — exact on the bounded snapshot."""
    adj: dict[str, set[str]] = defaultdict(set)
    ids = {str(n.get("id")) for n in nodes if n.get("id")}
    for e in edges:
        s, t = str(e.get("source") or ""), str(e.get("target") or "")
        if s in ids and t in ids:
            adj[s].add(t)
            adj[t].add(s)
    seen: set[str] = set()
    components: list[list[str]] = []
    for nid in sorted(ids):
        if nid in seen:
            continue
        stack = [nid]
        comp: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            for nxt in sorted(adj.get(cur, ())):
                if nxt not in seen:
                    stack.append(nxt)
        components.append(sorted(comp))
    components.sort(key=lambda c: (-len(c), c[0] if c else ""))
    degree = {nid: len(adj.get(nid, ())) for nid in ids}
    bridges = sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    return {
        "component_count": len(components),
        "components": [{"size": len(c), "node_ids": c[:50]} for c in components[:50]],
        "largest_component_size": len(components[0]) if components else 0,
        "bridge_nodes": [{"id": i, "degree": d} for i, d in bridges],
        "algorithm": "connected_components",
        "algorithm_version": ALGORITHM_VERSION,
        "exact": True,
        "sampled": False,
    }


def compute_derived_snapshot(
    facade: Any,
    *,
    limit: int = 1000,
    q: str | None = None,
    types: list[str] | None = None,
    algorithm: str = "connected_components",
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Build a derived graph snapshot + analysis from the bounded facade."""
    if cancel_check and cancel_check():
        raise RuntimeError("BRAIN_CANCELLED")
    safe_limit = max(10, min(int(limit), 1000))
    graph = facade.query(types=types, q=q, limit=safe_limit)
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    if cancel_check and cancel_check():
        raise RuntimeError("BRAIN_CANCELLED")
    analysis = _community_components(nodes, edges)
    payload = {
        "nodes": nodes,
        "edges": edges,
        "stats": graph.get("stats") or {},
        "truth": {
            **dict(graph.get("truth") or {}),
            "brain_is_facade": True,
            "derived_not_canonical": True,
            "not_a_brain_database": True,
            "advisory": True,
        },
        "analysis": analysis,
        "provenance": {
            "algorithm": algorithm,
            "algorithm_version": ALGORITHM_VERSION,
            "computed_at": utc_now(),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "limit": safe_limit,
            "filters": {"q": q, "types": types},
            "exact_on_bounded_snapshot": True,
            "global_truth": False,
        },
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    payload["provenance"]["content_hash"] = hashlib.sha256(raw).hexdigest()
    return payload


def process_brain_compute_job(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    store = ctx["job_store"]
    args = dict(getattr(job, "arguments", None) or {})
    capability = str(getattr(job, "capability_id", "") or "")
    action = str(
        args.get("action")
        or (
            capability.replace("brain.compute.", "").replace("brain.", "")
            if capability.startswith("brain.")
            else ""
        )
        or "snapshot"
    ).strip().lower()
    if action in {"compute.snapshot", "compute_snapshot"}:
        action = "snapshot"

    cancel_check = ctx.get("job_cancel_check")
    lease_lost = ctx.get("lease_lost")

    def _fence() -> bool:
        if callable(cancel_check) and cancel_check():
            return True
        if lease_lost is not None and getattr(lease_lost, "is_set", lambda: False)():
            return True
        return False

    try:
        facade = _build_facade(ctx)
        types = args.get("types")
        if isinstance(types, str):
            types = [t.strip() for t in types.split(",") if t.strip()]
        snapshot = compute_derived_snapshot(
            facade,
            limit=int(args.get("limit") or facade.max_nodes),
            q=args.get("q"),
            types=types if isinstance(types, list) else None,
            algorithm=str(args.get("algorithm") or "connected_components"),
            cancel_check=_fence,
        )
    except Exception as exc:  # noqa: BLE001
        code = "BRAIN_CANCELLED" if "CANCELLED" in str(exc) else "BRAIN_COMPUTE_FAILED"
        return _fail(
            store,
            job,
            f"{code}: {type(exc).__name__}: {exc}"[:500],
            metadata={"brain_action": action},
            ctx=ctx,
        )

    artifact_ref = None
    artifact_store = ctx.get("artifact_store")
    if artifact_store is not None and hasattr(artifact_store, "create_from_bytes"):
        try:
            body = json.dumps(snapshot, default=str).encode("utf-8")
            # Spill large snapshots; keep JobStore result bounded.
            if len(body) > 32_000 or action in {"snapshot", "rebuild", "recompute", "analyze"}:
                art = artifact_store.create_from_bytes(
                    body,
                    media_type="application/json",
                    filename=f"brain-{action}-{snapshot['provenance']['content_hash'][:12]}.json",
                    metadata={
                        "kind": "brain_derived_snapshot",
                        "algorithm": snapshot["provenance"]["algorithm"],
                        "algorithm_version": ALGORITHM_VERSION,
                        "node_count": snapshot["provenance"]["node_count"],
                        "edge_count": snapshot["provenance"]["edge_count"],
                    },
                )
                artifact_ref = (
                    art.public_dict()
                    if hasattr(art, "public_dict")
                    else {"artifact_id": getattr(art, "artifact_id", None)}
                )
        except Exception:  # noqa: BLE001 — snapshot still returned bounded
            artifact_ref = None

    # Enrichment proposals are advisory only — never assert Knowledge facts.
    proposals: list[dict[str, Any]] = []
    if action in {"enrich", "analyze"}:
        for bridge in (snapshot.get("analysis") or {}).get("bridge_nodes") or []:
            proposals.append(
                {
                    "kind": "bridge_node_advisory",
                    "node_id": bridge.get("id"),
                    "degree": bridge.get("degree"),
                    "advisory": True,
                    "truth": {"brain_does_not_assert_fact": True},
                }
            )

    result = {
        "action": action,
        "capability_id": capability,
        "node_count": snapshot["provenance"]["node_count"],
        "edge_count": snapshot["provenance"]["edge_count"],
        "analysis": snapshot.get("analysis"),
        "provenance": snapshot.get("provenance"),
        "proposals": proposals,
        "artifact": artifact_ref,
        # Bound inline stats; full graph lives in artifact when spilled.
        "stats": snapshot.get("stats"),
        "truth": {
            "brain_is_facade": True,
            "derived_not_canonical": True,
            "not_a_brain_database": True,
            "executed_via": "brain_compute_worker",
            "advisory": True,
        },
    }
    if artifact_ref is None:
        # Small graphs may stay inline (still bounded by facade max).
        result["nodes"] = snapshot.get("nodes")
        result["edges"] = snapshot.get("edges")
    return _complete(store, job, result, ctx=ctx)
