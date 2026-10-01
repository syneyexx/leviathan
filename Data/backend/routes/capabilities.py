"""Capability catalog / gateway HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.execution import CapabilityRequest, CapabilityStatus
from Data.modules.execution.overview import (
    build_capability_detail_projection,
    build_tools_library,
    build_tools_overview,
)


class CapabilityExecuteRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)
    approval_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    requested_by: str = "api"
    trace_id: str | None = None
    idempotency_key: str | None = None


class CustomCapabilityCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    wraps_capability_id: str = Field(min_length=1, max_length=160)
    capability_id: str | None = Field(default=None, max_length=120)
    version: str = Field(default="1.0.0", max_length=40)
    metadata: dict = Field(default_factory=dict)


class CustomCapabilityUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    version: str | None = Field(default=None, max_length=40)
    metadata: dict | None = None
    expected_revision: int | None = None


def build_capabilities_router(
    *,
    capability_catalog: Any,
    execution_gateway: Any,
    observation_store: Any,
    observability: Any,
    capability_receipts: Any,
    plugin_registry: Any = None,
    mcp_bridge: Any = None,
    function_registry: Any = None,
    custom_capability_store: Any = None,
) -> APIRouter:
    router = APIRouter(tags=["capabilities"])

    @router.get("/api/capabilities/overview")
    def capabilities_overview(period_days: Annotated[int, Query(ge=1, le=90)] = 7) -> dict:
        """Bounded Tools KPI / MCP / plugin / receipt projection."""
        return {
            "overview": build_tools_overview(
                capability_catalog=capability_catalog,
                capability_receipts=capability_receipts,
                plugin_registry=plugin_registry,
                mcp_bridge=mcp_bridge,
                function_registry=function_registry,
                period_days=period_days,
            )
        }

    @router.get("/api/capabilities/library")
    def capabilities_library(
        q: str | None = None,
        category: str | None = None,
        source: str | None = None,
        sort: str = Query("name", max_length=40),
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0, le=50_000),
    ) -> dict:
        return build_tools_library(
            capability_catalog=capability_catalog,
            capability_receipts=capability_receipts,
            plugin_registry=plugin_registry,
            function_registry=function_registry,
            q=q,
            category=category,
            source=source,
            sort=sort,
            limit=limit,
            offset=offset,
        )

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

    @router.get("/api/capabilities/receipts/by-capability/{capability_id}")
    def capability_receipts_by_capability(
        capability_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict:
        return {
            "capability_id": capability_id,
            "receipts": [
                item.public_dict()
                for item in capability_receipts.recent_for_capability(capability_id, limit=limit)
            ],
            "usage": capability_receipts.aggregate_for_capability(capability_id),
        }

    @router.get("/api/capabilities/custom")
    def list_custom_capabilities() -> dict:
        if custom_capability_store is None:
            return {"custom": [], "truth": {"custom_store_unavailable": True}}
        return {
            "custom": [item.public_dict() for item in custom_capability_store.list()],
            "truth": {"custom_wrappers_only": True},
        }

    @router.post("/api/capabilities/custom")
    def create_custom_capability(payload: CustomCapabilityCreateRequest) -> dict:
        if custom_capability_store is None:
            raise HTTPException(status_code=503, detail="Custom capability store unavailable")
        target = capability_catalog.get(payload.wraps_capability_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Wrapped capability not found")
        try:
            record = custom_capability_store.create(
                name=payload.name,
                description=payload.description,
                wraps_capability_id=payload.wraps_capability_id,
                capability_id=payload.capability_id,
                version=payload.version,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        custom_capability_store.hydrate_into_catalog(capability_catalog)
        definition = capability_catalog.get(record.capability_id)
        observability.emit(
            "capability",
            "custom_create",
            payload={"capability_id": record.capability_id, "wraps": record.wraps_capability_id},
        )
        return {
            "custom": record.public_dict(),
            "capability": definition.public_dict() if definition else None,
            "truth": {"custom_is_wrapper_not_exec": True},
        }

    @router.patch("/api/capabilities/custom/{capability_id}")
    def update_custom_capability(capability_id: str, payload: CustomCapabilityUpdateRequest) -> dict:
        if custom_capability_store is None:
            raise HTTPException(status_code=503, detail="Custom capability store unavailable")
        try:
            record = custom_capability_store.update(
                capability_id,
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                version=payload.version,
                metadata=payload.metadata,
                expected_revision=payload.expected_revision,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Custom capability not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        custom_capability_store.hydrate_into_catalog(capability_catalog)
        definition = capability_catalog.get(record.capability_id)
        return {
            "custom": record.public_dict(),
            "capability": definition.public_dict() if definition else None,
        }

    @router.delete("/api/capabilities/custom/{capability_id}")
    def delete_custom_capability(capability_id: str) -> dict:
        if custom_capability_store is None:
            raise HTTPException(status_code=503, detail="Custom capability store unavailable")
        record = custom_capability_store.get(capability_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Custom capability not found")
        meta = dict(record.metadata or {})
        if meta.get("system_protected") and not meta.get("force_unregister"):
            raise HTTPException(status_code=403, detail="Custom capability is system-protected")
        custom_capability_store.delete(capability_id)
        # True catalog removal (ownership-aware unregister), not soft-unavailable.
        if hasattr(capability_catalog, "unregister"):
            capability_catalog.unregister(capability_id)
        else:
            capability_catalog.set_availability(
                capability_id,
                available=False,
                reason="Custom capability deleted",
            )
        return {
            "ok": True,
            "capability_id": capability_id,
            "truth": {"catalog_unregistered": True, "soft_unavailable_is_not_removal": True},
        }

    @router.get("/api/capabilities/{capability_id}")
    def get_capability(
        capability_id: str,
        detail: bool = Query(False),
        receipt_limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict:
        definition = execution_gateway.get_capability(capability_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Capability not found")
        if not detail:
            return {"capability": definition.public_dict()}
        return build_capability_detail_projection(
            definition=definition,
            capability_receipts=capability_receipts,
            plugin_registry=plugin_registry,
            mcp_bridge=mcp_bridge,
            function_registry=function_registry,
            receipt_limit=receipt_limit,
        )

    @router.post("/api/capabilities/{capability_id}/execute")
    def execute_capability(capability_id: str, payload: CapabilityExecuteRequest) -> dict:
        if capability_id not in capability_catalog:
            raise HTTPException(status_code=404, detail="Capability not found")
        # Tools UI test path — refuse destructive side effects without approval.
        definition = capability_catalog.get(capability_id)
        if definition is not None and (payload.requested_by or "").startswith("tools-ui"):
            side = {e.value if hasattr(e, "value") else str(e) for e in definition.side_effects}
            dangerous = side & {"WRITE", "EXECUTE", "DELETE", "DESTRUCTIVE", "EXTERNAL_SIDE_EFFECT"}
            if dangerous and not payload.approval_id:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "dangerous_test_blocked",
                        "message": (
                            "Test invocation blocked for side effects: "
                            + ", ".join(sorted(dangerous))
                        ),
                        "side_effects": sorted(dangerous),
                        "truth": {"test_must_not_bypass_policy": True},
                    },
                )
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
        if result.status == CapabilityStatus.APPROVAL_REQUIRED:
            status_code = 403
        elif result.status == CapabilityStatus.REJECTED:
            reason = (result.telemetry or {}).get("reason")
            status_code = 403 if reason in {"approval_required", "approval_denied"} else 422
        elif result.status == CapabilityStatus.QUEUED:
            status_code = 202
        elif result.status == CapabilityStatus.TIMEOUT:
            status_code = 504
        elif result.status == CapabilityStatus.CANCELLED:
            status_code = 409
        elif result.status == CapabilityStatus.FAILED:
            status_code = 500
        if status_code == 202:
            return {"result": result.public_dict()}
        if status_code != 200:
            raise HTTPException(status_code=status_code, detail=result.public_dict())
        return {"result": result.public_dict()}

    return router
