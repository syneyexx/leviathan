"""Skills HTTP routes — installed + catalog skills over ExternalCapabilityStore."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class SkillEnableRequest(BaseModel):
    enabled: bool = True


def build_skills_router(*, external_store: Any, observability: Any = None) -> APIRouter:
    router = APIRouter(tags=["skills"])

    @router.get("/api/skills")
    def list_skills(
        query: str | None = None,
        include_catalog: bool = Query(default=False),
        enabled_only: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        rows = external_store.search_skills(
            query=query,
            enabled_only=enabled_only,
            include_catalog=include_catalog,
            limit=limit,
            offset=offset,
        )
        total_installed = external_store.count_skills(catalog_only=False)
        total_catalog = external_store.count_skills(catalog_only=True)
        return {
            "skills": rows,
            "count": len(rows),
            "offset": offset,
            "limit": limit,
            "totals": {"installed": total_installed, "catalog": total_catalog},
            "truth": {
                "skills_are_not_shell_authority": True,
                "instructions_load_on_demand": True,
                "catalog_not_prompt_injected": True,
            },
        }

    @router.get("/api/skills/{skill_id}")
    def get_skill(skill_id: str, include_instructions: bool = Query(default=False)) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        skill = external_store.get_skill(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        if include_instructions:
            from Data.modules.module_manager.external.skills import load_skill_instructions

            skill = {**skill, "instructions": load_skill_instructions(skill)}
        return {"skill": skill}

    @router.post("/api/skills/{skill_id}/enable")
    def enable_skill(skill_id: str, payload: SkillEnableRequest | None = None) -> dict:
        if external_store is None:
            raise HTTPException(status_code=503, detail="External capability store unavailable")
        payload = payload or SkillEnableRequest(enabled=True)
        updated = external_store.set_skill_enabled(skill_id, bool(payload.enabled))
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        if observability is not None:
            observability.emit(
                "external_capability",
                "skills.enabled" if payload.enabled else "skills.disabled",
                payload={"skill_id": skill_id},
            )
        return {"skill": updated}

    return router
