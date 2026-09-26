"""Verification engine / report HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.verification import VerificationRequirement


class VerifyRequest(BaseModel):
    run_id: str | None = None
    job_id: str | None = None
    requirements: list[dict] = Field(default_factory=list)


def build_verification_router(
    *,
    verification_engine: Any,
    verification_reports: Any,
    metrics: Any,
) -> APIRouter:
    router = APIRouter(tags=["verification"])

    @router.post("/api/verification/evaluate")
    def evaluate_verification(payload: VerifyRequest) -> dict:
        reqs: list[VerificationRequirement] = []
        for raw in payload.requirements:
            try:
                reqs.append(
                    VerificationRequirement(
                        requirement_id=str(raw.get("requirement_id") or raw.get("id") or f"req-{len(reqs)}"),
                        description=str(raw.get("description") or "requirement"),
                        evidence_kind=raw.get("evidence_kind"),
                        min_verified=int(raw.get("min_verified") or 1),
                        artifact_id=raw.get("artifact_id"),
                        path=raw.get("path"),
                        observation_id=raw.get("observation_id"),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Invalid requirement: {exc}") from exc
        report = verification_engine.verify(
            reqs,
            run_id=payload.run_id,
            job_id=payload.job_id,
        )
        verification_reports.save(report)
        metrics.incr("verification_evaluations")
        return {"report": report.public_dict()}

    @router.get("/api/verification/reports")
    def list_verification_reports(
        run_id: Annotated[str | None, Query()] = None,
        job_id: Annotated[str | None, Query()] = None,
        outcome: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> dict:
        items = verification_reports.list(
            run_id=run_id,
            job_id=job_id,
            outcome=outcome,
            limit=limit,
        )
        return {"reports": [item.public_dict() for item in items]}

    @router.get("/api/verification/reports/{report_id}")
    def get_verification_report(report_id: str) -> dict:
        item = verification_reports.get(report_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Verification report not found")
        return {"report": item.public_dict()}

    return router
