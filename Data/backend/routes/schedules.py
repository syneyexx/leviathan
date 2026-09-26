"""Schedule store / runner HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.schedules import ScheduleStatus, ScheduleTargetKind


class ScheduleCreateRequest(BaseModel):
    name: str = Field(default="schedule", min_length=1, max_length=120)
    target_kind: str = "JOB"
    target_ref: str = Field(min_length=1, max_length=120)
    interval_seconds: int = Field(default=60, ge=1, le=86_400)
    target_payload: dict = Field(default_factory=dict)
    start_after_seconds: int = Field(default=0, ge=0, le=86_400)


def build_schedules_router(
    *,
    schedule_store: Any,
    schedule_runner: Any,
    observability: Any,
) -> APIRouter:
    router = APIRouter(tags=["schedules"])

    @router.get("/api/schedules")
    def list_schedules(
        status: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict:
        parsed = None
        if status:
            try:
                parsed = ScheduleStatus(status.upper())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid schedule status: {status}") from exc
        return {
            "schedules": [item.public_dict() for item in schedule_store.list(status=parsed, limit=limit)],
            "telemetry": dict(schedule_runner.telemetry),
        }

    @router.post("/api/schedules")
    def create_schedule(payload: ScheduleCreateRequest) -> dict:
        try:
            kind = ScheduleTargetKind(payload.target_kind.upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid target_kind: {payload.target_kind}") from exc
        try:
            record = schedule_store.create(
                name=payload.name,
                target_kind=kind,
                target_ref=payload.target_ref,
                interval_seconds=payload.interval_seconds,
                target_payload=payload.target_payload,
                start_after_seconds=payload.start_after_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"schedule": record.public_dict()}

    @router.get("/api/schedules/{schedule_id}")
    def get_schedule(schedule_id: str) -> dict:
        record = schedule_store.get(schedule_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"schedule": record.public_dict()}

    @router.post("/api/schedules/{schedule_id}/pause")
    def pause_schedule(schedule_id: str) -> dict:
        record = schedule_store.set_status(schedule_id, ScheduleStatus.PAUSED)
        if record is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"schedule": record.public_dict()}

    @router.post("/api/schedules/{schedule_id}/resume")
    def resume_schedule(schedule_id: str) -> dict:
        record = schedule_store.set_status(schedule_id, ScheduleStatus.ACTIVE)
        if record is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"schedule": record.public_dict()}

    @router.post("/api/schedules/tick")
    def tick_schedules() -> dict:
        fired = schedule_runner.tick()
        observability.emit(
            "schedule",
            "tick",
            payload={"fired": len(fired), "ok": sum(1 for item in fired if item.get("ok"))},
        )
        return {"fired": fired, "telemetry": dict(schedule_runner.telemetry)}

    return router
