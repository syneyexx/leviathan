"""Evidence service HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.evidence import EvidenceStatus


class EvidenceArtifactClaim(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=120)
    claim: str | None = None
    observation_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    verify_now: bool = True


class EvidenceFileClaim(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    claim: str | None = None
    observation_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None


class EvidenceObservationClaim(BaseModel):
    observation_id: str = Field(min_length=1, max_length=120)
    claim: str | None = None
    run_id: str | None = None
    job_id: str | None = None


def build_evidence_router(*, evidence_service: Any) -> APIRouter:
    router = APIRouter(tags=["evidence"])

    @router.get("/api/evidence")
    def list_evidence(
        status: Annotated[str | None, Query()] = None,
        run_id: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict:
        parsed = None
        if status:
            try:
                parsed = EvidenceStatus(status.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid evidence status: {status}") from exc
        items = evidence_service.store.list(status=parsed, run_id=run_id, limit=limit)
        return {"evidence": [item.public_dict() for item in items]}

    @router.get("/api/evidence/{evidence_id}")
    def get_evidence(evidence_id: str) -> dict:
        item = evidence_service.store.get(evidence_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
        return {"evidence": item.public_dict()}

    @router.post("/api/evidence/artifact")
    def claim_artifact_evidence(payload: EvidenceArtifactClaim) -> dict:
        try:
            record = evidence_service.claim_artifact_hash(
                artifact_id=payload.artifact_id,
                claim=payload.claim,
                observation_id=payload.observation_id,
                run_id=payload.run_id,
                job_id=payload.job_id,
                verify_now=payload.verify_now,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"evidence": record.public_dict()}

    @router.post("/api/evidence/file")
    def claim_file_evidence(payload: EvidenceFileClaim) -> dict:
        record = evidence_service.claim_file_exists(
            path=payload.path,
            claim=payload.claim,
            observation_id=payload.observation_id,
            run_id=payload.run_id,
            job_id=payload.job_id,
        )
        return {"evidence": record.public_dict()}

    @router.post("/api/evidence/observation")
    def claim_observation_evidence(payload: EvidenceObservationClaim) -> dict:
        record = evidence_service.claim_observation_ref(
            observation_id=payload.observation_id,
            claim=payload.claim,
            run_id=payload.run_id,
            job_id=payload.job_id,
        )
        return {"evidence": record.public_dict()}

    @router.post("/api/evidence/{evidence_id}/verify")
    def verify_evidence(evidence_id: str) -> dict:
        try:
            record = evidence_service.verify(evidence_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Evidence not found") from exc
        return {"evidence": record.public_dict()}

    return router
