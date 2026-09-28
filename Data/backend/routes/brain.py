"""Brain graph HTTP surface — bounded reads inline; heavy compute external."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from Data.modules.brain import BrainQueryFacade


class BrainComputeRequest(BaseModel):
    action: str = Field(default="snapshot", max_length=64)
    limit: int = Field(default=1000, ge=10, le=1000)
    q: str | None = Field(default=None, max_length=200)
    types: list[str] | None = None
    algorithm: str = Field(default="connected_components", max_length=64)


def _runners_externalized() -> bool:
    ext = (os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API") or "").strip().lower()
    if ext in {"1", "true", "yes", "on"}:
        return True
    if ext in {"0", "false", "no", "off"}:
        return False
    try:
        from Data.modules.workers.settings import load_worker_settings

        return bool(load_worker_settings().externalize_api_runners)
    except Exception:  # noqa: BLE001
        return False


def build_brain_router(
    facade: BrainQueryFacade,
    *,
    job_runtime: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["brain"])

    @router.get("/api/brain/graph")
    def brain_graph(
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        q: Annotated[str | None, Query(max_length=200)] = None,
        types: Annotated[str | None, Query(description="Comma-separated type filters")] = None,
        root: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        type_list = [t.strip() for t in (types or "").split(",") if t.strip()] or None
        return facade.query(types=type_list, q=q, limit=limit, root=root)

    @router.get("/api/brain/stats")
    def brain_stats() -> dict[str, Any]:
        # Bounded projection only — never a full-corpus heavy recompute.
        graph = facade.query(limit=facade.max_nodes)
        truth = dict(graph.get("truth") or {})
        truth.setdefault("bounded_projection", True)
        truth.setdefault("stats_are_not_global_unless_corpus_fits_bound", True)
        return {
            "stats": graph["stats"],
            "truth": truth,
        }

    @router.post("/api/brain/compute")
    def brain_compute(
        response: Response,
        payload: BrainComputeRequest | None = None,
    ) -> dict[str, Any]:
        """Enqueue heavy derived Brain computation (brain_compute pool)."""
        body = payload or BrainComputeRequest()
        action = (body.action or "snapshot").strip().lower()
        cap_map = {
            "snapshot": "brain.compute.snapshot",
            "rebuild": "brain.rebuild",
            "recompute": "brain.recompute",
            "enrich": "brain.enrich",
            "analyze": "brain.analyze",
        }
        capability = cap_map.get(action, "brain.compute.snapshot")
        if not _runners_externalized():
            # Test / legacy: run derived compute in-process via same module.
            from Data.modules.brain.compute import compute_derived_snapshot

            snap = compute_derived_snapshot(
                facade,
                limit=body.limit,
                q=body.q,
                types=body.types,
                algorithm=body.algorithm,
            )
            return {
                "queued": False,
                "action": action,
                "result": {
                    "node_count": snap["provenance"]["node_count"],
                    "edge_count": snap["provenance"]["edge_count"],
                    "analysis": snap.get("analysis"),
                    "provenance": snap.get("provenance"),
                    "truth": snap.get("truth"),
                },
            }
        if job_runtime is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "BRAIN_COMPUTE_UNAVAILABLE",
                        "message": "JobRuntime not bound; cannot enqueue brain compute",
                    }
                },
            )
        job = job_runtime.enqueue(
            capability_id=capability,
            arguments={
                "action": action,
                "limit": body.limit,
                "q": body.q,
                "types": body.types,
                "algorithm": body.algorithm,
            },
            requested_by="api.brain.compute",
            domain="brain",
            worker_pool="brain_compute",
            resource_class="CPU_HEAVY",
            latency_class="background",
            metadata={
                "execution_class": "EXTERNAL_REQUIRED",
                "truth": {
                    "brain_is_facade": True,
                    "derived_not_canonical": True,
                },
            },
        )
        response.status_code = 202
        return {
            "queued": True,
            "job": job.public_dict(),
            "job_id": job.job_id,
            "action": action,
            "truth": {
                "executed_via": "brain_compute_worker",
                "brain_is_facade": True,
                "fastapi_does_not_heavy_compute": True,
                "bounded_graph_reads_remain_inline": True,
            },
        }

    return router
