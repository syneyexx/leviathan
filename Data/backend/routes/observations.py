"""Observation store HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query


def build_observations_router(*, observation_store: Any) -> APIRouter:
    router = APIRouter(tags=["observations"])

    @router.get("/api/observations")
    def list_observations(
        capability_id: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict:
        items = observation_store.list_observations(capability_id=capability_id, limit=limit)
        return {"observations": [item.public_dict() for item in items]}

    @router.get("/api/observations/{observation_id}")
    def get_observation(observation_id: str) -> dict:
        item = observation_store.get_observation(observation_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Observation not found")
        return {"observation": item.public_dict()}

    return router
