"""System telemetry HTTP surface."""

from __future__ import annotations

from fastapi import APIRouter

from Data.modules.observability import SystemTelemetrySampler


def build_system_telemetry_router(sampler: SystemTelemetrySampler) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/api/system/telemetry")
    def system_telemetry() -> dict:
        return sampler.latest_public()

    return router
