"""FastAPI routes for the Research workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.research import ResearchError, ResearchService


def raise_research_error(exc: ResearchError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class ProjectCreate(BaseModel):
    title: str | None = None
    topic: str
    objective: str = ""
    depth: str = "standard"
    allowWeb: bool = False
    respectRobotsTxt: bool = True
    modelProfile: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    localScopes: list[str] = Field(default_factory=list)
    seedSources: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    title: str | None = None
    topic: str | None = None
    objective: str | None = None
    depth: str | None = None
    allowWeb: bool | None = None
    respectRobotsTxt: bool | None = None
    modelProfile: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    localScopes: list[str] | None = None
    seedSources: list[str] | None = None


class PlanRequest(BaseModel):
    interpretedQuestion: str | None = None
    scope: str | None = None
    assumptions: list[str] | None = None
    subquestions: list[str] | None = None
    retrievalQueries: list[str] | None = None
    preferredSourceTypes: list[str] | None = None
    localScopes: list[str] | None = None
    exclusionCriteria: list[str] | None = None
    rounds: int | None = None
    budget: dict[str, Any] | None = None
    notes: str | None = None


class DeepenRequest(BaseModel):
    extraRounds: int = 1


def build_research_router(service: ResearchService) -> APIRouter:
    router = APIRouter(tags=["research"])

    @router.get("/api/research/budgets")
    def budgets() -> dict:
        return {"presets": service.list_budget_presets()}

    @router.get("/api/research")
    def list_projects(limit: int = Query(100, ge=1, le=500)) -> dict:
        projects = [p.public_dict() for p in service.list_projects(limit=limit)]
        return {"projects": projects}

    @router.post("/api/research")
    def create_project(payload: ProjectCreate) -> dict:
        try:
            project = service.create_project(
                title=payload.title,
                topic=payload.topic,
                objective=payload.objective,
                depth=payload.depth,
                allow_web=payload.allowWeb,
                respect_robots_txt=payload.respectRobotsTxt,
                model_profile=payload.modelProfile,
                budget_overrides=payload.budget,
                local_scopes=payload.localScopes,
                seed_sources=payload.seedSources,
            )
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.get("/api/research/{project_id}")
    def get_project(project_id: str) -> dict:
        try:
            project = service.get_project(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.put("/api/research/{project_id}")
    def update_project(project_id: str, payload: ProjectUpdate) -> dict:
        try:
            project = service.update_project(
                project_id,
                {
                    "title": payload.title,
                    "topic": payload.topic,
                    "objective": payload.objective,
                    "depth": payload.depth,
                    "allow_web": payload.allowWeb,
                    "respect_robots_txt": payload.respectRobotsTxt,
                    "model_profile": payload.modelProfile,
                    "budget": payload.budget,
                    "local_scopes": payload.localScopes,
                    "seed_sources": payload.seedSources,
                },
            )
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.post("/api/research/{project_id}/plan")
    def plan_project(project_id: str, payload: PlanRequest | None = None) -> dict:
        edits: dict[str, Any] = {}
        if payload is not None:
            mapping = {
                "interpreted_question": payload.interpretedQuestion,
                "scope": payload.scope,
                "assumptions": payload.assumptions,
                "subquestions": payload.subquestions,
                "retrieval_queries": payload.retrievalQueries,
                "preferred_source_types": payload.preferredSourceTypes,
                "local_scopes": payload.localScopes,
                "exclusion_criteria": payload.exclusionCriteria,
                "rounds": payload.rounds,
                "budget": payload.budget,
                "notes": payload.notes,
            }
            edits = {k: v for k, v in mapping.items() if v is not None}
        try:
            project = service.plan(project_id, edits=edits or None)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict(), "plan": project.plan.public_dict() if project.plan else None}

    @router.post("/api/research/{project_id}/run")
    def run_project(project_id: str) -> dict:
        try:
            project = service.run(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.post("/api/research/{project_id}/cancel")
    def cancel_project(project_id: str) -> dict:
        try:
            project = service.cancel(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.post("/api/research/{project_id}/resume")
    def resume_project(project_id: str) -> dict:
        try:
            project = service.resume(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.post("/api/research/{project_id}/deepen")
    def deepen_project(project_id: str, payload: DeepenRequest | None = None) -> dict:
        extra = payload.extraRounds if payload else 1
        try:
            project = service.deepen(project_id, extra_rounds=extra)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"project": project.public_dict()}

    @router.get("/api/research/{project_id}/events")
    def events(project_id: str, limit: int = Query(200, ge=1, le=2000)) -> dict:
        try:
            items = service.list_events(project_id, limit=limit)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"events": [e.public_dict() for e in items]}

    @router.get("/api/research/{project_id}/sources")
    def sources(project_id: str, limit: int = Query(200, ge=1, le=2000)) -> dict:
        try:
            items = service.list_sources(project_id, limit=limit)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"sources": [s.public_dict() for s in items]}

    @router.get("/api/research/{project_id}/evidence")
    def evidence(project_id: str, limit: int = Query(500, ge=1, le=5000)) -> dict:
        try:
            items = service.list_evidence(project_id, limit=limit)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"evidence": [e.public_dict() for e in items]}

    @router.get("/api/research/{project_id}/claims")
    def claims(project_id: str, limit: int = Query(500, ge=1, le=5000)) -> dict:
        try:
            items = service.list_claims(project_id, limit=limit)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"claims": [c.public_dict() for c in items]}

    @router.get("/api/research/{project_id}/conflicts")
    def conflicts(project_id: str, limit: int = Query(200, ge=1, le=2000)) -> dict:
        try:
            items = service.list_conflicts(project_id, limit=limit)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"conflicts": [c.public_dict() for c in items]}

    @router.get("/api/research/{project_id}/coverage")
    def coverage(project_id: str) -> dict:
        try:
            summary = service.coverage(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"coverage": summary.public_dict()}

    @router.get("/api/research/{project_id}/report")
    def get_report(project_id: str) -> dict:
        try:
            report = service.get_report(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"report": report.public_dict()}

    @router.post("/api/research/{project_id}/report")
    def regenerate_report(project_id: str) -> dict:
        try:
            report = service.regenerate_report(project_id)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"report": report.public_dict()}

    @router.get("/api/research/{project_id}/export")
    def export_report(
        project_id: str,
        format: str = Query("markdown", pattern="^(markdown|md|html|json)$"),
    ) -> dict:
        try:
            bundle = service.export(project_id, fmt=format)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"export": bundle}

    @router.get("/api/research/{project_id}/citations/{citation_key}")
    def resolve_citation(project_id: str, citation_key: str) -> dict:
        try:
            resolution = service.resolve_citation(project_id, citation_key)
        except ResearchError as exc:
            raise_research_error(exc)
        return {"citation": resolution.public_dict()}

    return router
