"""Approval service HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from Data.modules.approvals import ApprovalStatus


class ApprovalCreateRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=120)
    reason: str | None = None
    run_id: str | None = None
    requested_by: str = "api"
    single_use: bool = True
    arguments: dict = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = "operator"
    reason: str | None = None


def build_approvals_router(
    *,
    approval_service: Any,
    capability_catalog: Any,
    assert_loopback_fn: Callable[[Request], None],
) -> APIRouter:
    router = APIRouter(tags=["approvals"])

    @router.get("/api/approvals")
    def list_approvals(
        status: Annotated[str | None, Query()] = None,
        capability_id: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict:
        parsed_status = None
        if status:
            try:
                parsed_status = ApprovalStatus(status.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid status: {status}") from exc
        items = approval_service.list(
            status=parsed_status,
            capability_id=capability_id,
            limit=limit,
        )
        return {"approvals": [item.public_dict() for item in items]}

    @router.post("/api/approvals")
    def create_approval(payload: ApprovalCreateRequest) -> dict:
        definition = capability_catalog.get(payload.capability_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Capability not found")
        decision = approval_service.evaluate_policy(definition.side_effects)
        if not decision.requires_approval:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Capability does not require approval",
                    "policy": decision.public_dict(),
                },
            )
        record = approval_service.request(
            capability_id=definition.id,
            side_effects=definition.side_effects,
            requested_by=payload.requested_by,
            reason=payload.reason,
            run_id=payload.run_id,
            single_use=payload.single_use,
            arguments=payload.arguments or None,
        )
        return {"approval": record.public_dict(), "policy": decision.public_dict()}

    @router.get("/api/approvals/{approval_id}")
    def get_approval(approval_id: str) -> dict:
        record = approval_service.get(approval_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        return {"approval": record.public_dict()}

    @router.post("/api/approvals/{approval_id}/approve")
    def approve_approval(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> dict:
        assert_loopback_fn(request)
        try:
            record = approval_service.approve(
                approval_id,
                decided_by=payload.decided_by,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval": record.public_dict()}

    @router.post("/api/approvals/{approval_id}/deny")
    def deny_approval(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> dict:
        assert_loopback_fn(request)
        try:
            record = approval_service.deny(
                approval_id,
                decided_by=payload.decided_by,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval": record.public_dict()}

    return router
