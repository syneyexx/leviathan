"""Read-only HTTP projections for the LEVIATHAN backend host.

These routes do not start processes, mutate jobs, or open a second control plane.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from Data.modules.host_console.liveness import build_host_liveness
from Data.modules.host_console.read_model import (
    build_host_overview,
    build_native_operations_read_model,
    build_source_ingestion_read_model,
)


def build_host_console_router(
    *,
    settings: Any,
    job_runtime: Any,
    observability: Any,
    sqlite_manager: Any,
    probe_fn: Any | None = None,
    version: str = "",
) -> APIRouter:
    router = APIRouter(tags=["host-console"])

    @router.get("/api/host/liveness")
    def host_liveness() -> dict[str, Any]:
        """Cheap process liveness for the native host readiness probe.

        FastAPI only serves this after lifespan startup completes, so a
        successful response proves API process liveness + bootstrap completion.
        """
        return build_host_liveness(version=version, bootstrapped=True)

    @router.get("/api/host/overview")
    def host_overview() -> dict[str, Any]:
        return build_host_overview(
            settings=settings,
            sqlite_manager=sqlite_manager,
            job_runtime=job_runtime,
            probe_fn=probe_fn,
            version=version,
        )

    @router.get("/api/host/source-ingestion")
    def host_source_ingestion(
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        return build_source_ingestion_read_model(
            settings=settings,
            job_runtime=job_runtime,
            limit=limit,
        )

    @router.get("/api/host/native-operations")
    def host_native_operations(
        limit: int = Query(default=40, ge=1, le=100),
    ) -> dict[str, Any]:
        return build_native_operations_read_model(
            observability=observability,
            probe_fn=probe_fn,
            limit=limit,
        )

    return router
