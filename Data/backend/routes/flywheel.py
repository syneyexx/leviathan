"""Post-training flywheel HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class ChallengerProposeRequest(BaseModel):
    challenger_model_id: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=2000)
    champion_model_id: str | None = None
    training_job_id: str | None = None


class PromoteRequest(BaseModel):
    decided_by: str = Field(min_length=1, max_length=120)
    eval_report_id: str | None = None
    require_eval_gate: bool = True
    suite_id: str = "foundation"


class RollbackRequest(BaseModel):
    decided_by: str = Field(min_length=1, max_length=120)


def build_flywheel_router(*, settings: Any, flywheel: Any) -> APIRouter:
    router = APIRouter(tags=["flywheel"])

    @router.post("/api/flywheel/challengers")
    def propose_challenger(payload: ChallengerProposeRequest) -> dict:
        if not settings.features.posttraining_flywheel:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_POSTTRAINING_FLYWHEEL=false"})
        proposal = flywheel.propose_challenger(
            challenger_model_id=payload.challenger_model_id,
            rationale=payload.rationale,
            champion_model_id=payload.champion_model_id,
            training_job_id=payload.training_job_id,
        )
        return {"proposal": proposal.public_dict()}

    @router.get("/api/flywheel/challengers")
    def list_challengers(limit: int = 50) -> dict:
        return {"proposals": [p.public_dict() for p in flywheel.list_proposals(limit=limit)]}

    @router.post("/api/flywheel/challengers/{proposal_id}/promote")
    def promote_challenger(proposal_id: str, payload: PromoteRequest) -> dict:
        if not settings.features.posttraining_flywheel:
            raise HTTPException(status_code=501, detail={"reason": "LEVIATHAN_FEATURE_POSTTRAINING_FLYWHEEL=false"})
        try:
            record = flywheel.promote(
                proposal_id,
                decided_by=payload.decided_by,
                eval_report_id=payload.eval_report_id,
                require_eval_gate=payload.require_eval_gate,
                suite_id=payload.suite_id,
            )
        except Exception as exc:  # noqa: BLE001
            from Data.modules.training import PromotionError

            if isinstance(exc, PromotionError):
                raise HTTPException(status_code=403, detail=exc.public_dict()) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"promotion": record.public_dict()}

    @router.post("/api/flywheel/promotions/{promotion_id}/rollback")
    def rollback_promotion(promotion_id: str, payload: RollbackRequest) -> dict:
        try:
            record = flywheel.rollback(promotion_id, decided_by=payload.decided_by)
        except Exception as exc:  # noqa: BLE001
            from Data.modules.training import PromotionError

            if isinstance(exc, PromotionError):
                raise HTTPException(status_code=403, detail=exc.public_dict()) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"promotion": record.public_dict()}

    @router.get("/api/flywheel/promotions")
    def list_promotions(limit: int = 50) -> dict:
        return {"promotions": flywheel.list_promotions(limit=limit)}

    @router.get("/api/flywheel/lineage/{model_id}")
    def get_model_lineage(model_id: str, limit: int = 100) -> dict:
        edges = flywheel.lineage.list_for_model(model_id, limit=limit)
        return {"model_id": model_id, "edges": [e.public_dict() for e in edges]}

    return router
