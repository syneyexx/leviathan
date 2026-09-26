"""Capability catalog / gateway HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus


class CapabilityExecuteRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    requested_by: str = "api"
    trace_id: str | None = None
    idempotency_key: str | None = None


def build_capabilities_router(
    *,
    capability_catalog: Any,
    execution_gateway: Any,
    observation_store: Any,
    observability: Any,
    capability_receipts: Any,
) -> APIRouter:
    router = APIRouter(tags=["capabilities"])

    @router.get("/api/capabilities")
    def list_capabilities(q: str | None = None, limit: int = Query(200, ge=1, le=500)) -> dict:
        if q:
            items = capability_catalog.search(q, limit=limit)
        else:
            items = execution_gateway.list_capabilities()[:limit]
        return {
            "capabilities": [item.public_dict() for item in items],
            "telemetry": dict(execution_gateway.telemetry),
            "effects_recorded": len(execution_gateway.effect_ledger),
            "truth": {"capability_search_avoids_prompt_schema_explosion": True},
        }

    @router.get("/api/capabilities/search")
    def search_capabilities(q: str = Query("", max_length=240), limit: int = Query(20, ge=1, le=100)) -> dict:
        items = capability_catalog.search(q, limit=limit)
        return {
            "query": q,
            "capabilities": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "provider_kind": item.provider_kind.value,
                    "available": item.available,
                    "side_effects": [e.value for e in item.side_effects],
                }
                for item in items
            ],
            "truth": {"shortlist_not_full_schema_dump": True},
        }

    @router.get("/api/capabilities/effects/recent")
    def recent_capability_effects(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
        durable = observation_store.list_effects(limit=limit)
        if durable:
            return {"effects": [item.public_dict() for item in durable], "source": "durable"}
        items = execution_gateway.effect_ledger[-limit:]
        return {
            "source": "memory",
            "effects": [
                {
                    "effect_id": item.effect_id,
                    "request_id": item.request_id,
                    "capability_id": item.capability_id,
                    "side_effects": list(item.side_effects),
                    "status": item.status,
                    "provider_kind": item.provider_kind,
                    "provider_ref": item.provider_ref,
                    "recorded_at_ms": item.recorded_at_ms,
                    "approval_id": item.approval_id,
                    "error": item.error,
                    "observation_id": item.observation_id,
                }
                for item in reversed(items)
            ],
        }

    @router.get("/api/capabilities/receipts/recent")
    def recent_capability_receipts(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
        return {"receipts": [item.public_dict() for item in capability_receipts.recent(limit=limit)]}

    @router.get("/api/capabilities/receipts/by-run/{run_id}")
    def capability_receipts_by_run(run_id: str, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> dict:
        return {
            "run_id": run_id,
            "receipts": [item.public_dict() for item in capability_receipts.list_for_run(run_id, limit=limit)],
        }

    @router.get("/api/capabilities/{capability_id}")
    def get_capability(capability_id: str) -> dict:
        definition = execution_gateway.get_capability(capability_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Capability not found")
        return {"capability": definition.public_dict()}

    @router.post("/api/capabilities/{capability_id}/execute")
    def execute_capability(capability_id: str, payload: CapabilityExecuteRequest) -> dict:
        if capability_id not in capability_catalog:
            raise HTTPException(status_code=404, detail="Capability not found")
        result = execution_gateway.execute(
            CapabilityRequest(
                capability_id=capability_id,
                arguments=payload.arguments,
                approval_id=payload.approval_id,
                run_id=payload.run_id,
                job_id=payload.job_id,
                requested_by=payload.requested_by,
                trace_id=payload.trace_id,
                idempotency_key=payload.idempotency_key,
            )
        )
        observability.emit(
            "capability",
            "execute",
            payload={
                "capability_id": capability_id,
                "status": result.status.value,
                "request_id": result.request_id,
            },
            level="info" if result.status.value == "COMPLETED" else "warn",
        )
        status_code = 200
        if result.status == CapabilityStatus.REJECTED:
            reason = (result.telemetry or {}).get("reason")
            status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
        elif result.status == CapabilityStatus.TIMEOUT:
            status_code = 504
        elif result.status == CapabilityStatus.CANCELLED:
            status_code = 409
        elif result.status == CapabilityStatus.FAILED:
            status_code = 500
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.public_dict())
        return {"result": result.public_dict()}

    return router
