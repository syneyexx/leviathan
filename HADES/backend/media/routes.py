"""FastAPI routes for HADES Media Intelligence."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, Field

import fastapi_nested_annotations  # noqa: F401 — nested PEP 563 OpenAPI fix
from media.models import ChannelCreate, ChannelUpdate, ProjectCreate, PublishApprove, SourceIngest


def mount_media_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(tags=["media"])

    def service():
        media = ctx.get("media")
        if media is None:
            raise HTTPException(status_code=503, detail="Media subsystem unavailable")
        return media

    @router.get("/media/capabilities")
    async def media_capabilities() -> dict[str, Any]:
        return service().capabilities()

    @router.get("/media/overview")
    async def media_overview() -> dict[str, Any]:
        return service().overview()

    @router.get("/media/setup")
    async def media_setup() -> dict[str, Any]:
        return service().setup_checklist()

    @router.get("/media/channels")
    async def list_channels(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        items = service().store.list_channels(limit=limit, offset=offset)
        return {"items": items, "limit": limit, "offset": offset}

    @router.post("/media/channels", status_code=status.HTTP_201_CREATED)
    async def create_channel(payload: ChannelCreate) -> dict[str, Any]:
        return {"channel": service().create_channel(payload)}

    @router.get("/media/channels/{channel_id}")
    async def get_channel(channel_id: str) -> dict[str, Any]:
        channel = service().store.get_channel(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="channel_not_found")
        return {"channel": channel}

    @router.patch("/media/channels/{channel_id}")
    async def patch_channel(channel_id: str, payload: ChannelUpdate) -> dict[str, Any]:
        channel = service().update_channel(channel_id, payload)
        if not channel:
            raise HTTPException(status_code=404, detail="channel_not_found")
        return {"channel": channel}

    @router.get("/media/projects")
    async def list_projects(
        channel_id: str | None = None,
        stage: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        items = service().store.list_projects(channel_id=channel_id, stage=stage, limit=limit, offset=offset)
        return {"items": items, "limit": limit, "offset": offset}

    @router.post("/media/projects", status_code=status.HTTP_201_CREATED)
    async def create_project(payload: ProjectCreate) -> dict[str, Any]:
        try:
            project = service().create_project(payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"project": project}

    @router.get("/media/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        project = service().store.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="project_not_found")
        return {
            "project": project,
            "events": service().store.list_project_events(project_id),
            "script": service().store.latest_script(project_id),
            "storyboard": service().store.latest_storyboard(project_id),
            "assets": service().store.list_assets(project_id=project_id),
            "variants": service().store.list_variants(project_id),
            "claims": service().store.list_research_claims(project_id),
            "publish_jobs": service().store.list_publish_jobs(project_id=project_id),
        }

    class RunProjectInput(BaseModel):
        max_stages: int = Field(default=30, ge=1, le=40)

    @router.post("/media/projects/{project_id}/run")
    async def run_project(project_id: str, payload: RunProjectInput | None = Body(default=None)) -> dict[str, Any]:
        body = payload or RunProjectInput()
        result = await service().run_project(project_id, max_stages=body.max_stages)
        if not result.get("ok") and result.get("error") == "project_not_found":
            raise HTTPException(status_code=404, detail="project_not_found")
        return result

    @router.post("/media/projects/{project_id}/cancel")
    async def cancel_project(project_id: str) -> dict[str, Any]:
        project = service().orchestrator.cancel_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="project_not_found")
        return {"project": project}

    class RetryStageInput(BaseModel):
        stage: str = Field(min_length=1, max_length=64)

    @router.post("/media/projects/{project_id}/retry-stage")
    async def retry_stage(project_id: str, payload: RetryStageInput) -> dict[str, Any]:
        result = await service().orchestrator.retry_stage(project_id, payload.stage)
        if result.get("error") == "project_not_found":
            raise HTTPException(status_code=404, detail="project_not_found")
        if result.get("error") == "invalid_stage":
            raise HTTPException(status_code=400, detail="invalid_stage")
        return result

    @router.post("/media/sources", status_code=status.HTTP_201_CREATED)
    async def ingest_source(payload: SourceIngest) -> dict[str, Any]:
        return {"source": service().ingest_source(payload)}

    @router.get("/media/trends")
    async def list_trends(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return {"items": service().store.list_trends(limit=limit)}

    class TrendDiscoverInput(BaseModel):
        query: str = Field(default="", max_length=400)
        channel_id: str | None = Field(default=None, max_length=80)

    @router.post("/media/trends/discover")
    async def discover_trends(payload: TrendDiscoverInput) -> dict[str, Any]:
        return await service().discover_trends(query=payload.query, channel_id=payload.channel_id)

    @router.get("/media/opportunities")
    async def list_opportunities(
        channel_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": service().store.list_opportunities(channel_id=channel_id, limit=limit)}

    @router.get("/media/ideas")
    async def list_ideas(
        channel_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": service().store.list_ideas(channel_id=channel_id, limit=limit)}

    @router.get("/media/assets")
    async def list_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {"items": service().store.list_assets(project_id=project_id, limit=limit)}

    @router.get("/media/publish")
    async def list_publish_jobs(
        status_filter: str | None = Query(default=None, alias="status"),
        project_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": service().store.list_publish_jobs(status=status_filter, project_id=project_id, limit=limit)}

    @router.post("/media/publish/approve")
    async def approve_publish(payload: PublishApprove) -> dict[str, Any]:
        jobs = service().publishing.approve_jobs(payload.job_ids, platform_consent=payload.platform_consent)
        return {"items": jobs}

    @router.post("/media/publish/{job_id}/execute")
    async def execute_publish(job_id: str) -> dict[str, Any]:
        result = service().publishing.publish_job(job_id)
        if result.get("error") == "job_not_found":
            raise HTTPException(status_code=404, detail="job_not_found")
        return result

    @router.post("/media/publish/{job_id}/reconcile")
    async def reconcile_publish(job_id: str) -> dict[str, Any]:
        result = service().publishing.reconcile_job(job_id)
        if result.get("error") == "job_not_found":
            raise HTTPException(status_code=404, detail="job_not_found")
        return result

    @router.get("/media/analytics")
    async def analytics(
        platform: str | None = None,
        external_post_id: str | None = None,
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {
            "items": service().store.list_metric_snapshots(
                platform=platform,
                external_post_id=external_post_id,
                project_id=project_id,
                limit=limit,
            )
        }

    @router.get("/media/experiments")
    async def list_experiments(
        channel_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": service().store.list_experiments(channel_id=channel_id, limit=limit)}

    class ExperimentCreate(BaseModel):
        channel_id: str | None = None
        name: str = Field(min_length=1, max_length=200)
        hypothesis: str = Field(default="", max_length=2000)
        control: dict[str, Any] = Field(default_factory=dict)
        variant: dict[str, Any] = Field(default_factory=dict)
        primary_metric: str = Field(default="average_view_percentage", max_length=80)
        min_samples: int = Field(default=20, ge=5, le=1000)

    @router.post("/media/experiments", status_code=status.HTTP_201_CREATED)
    async def create_experiment(payload: ExperimentCreate) -> dict[str, Any]:
        return {"experiment": service().experiments.create(**payload.model_dump())}

    @router.get("/media/learning")
    async def list_learning(
        channel_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": service().store.list_learning_findings(channel_id=channel_id, limit=limit)}

    @router.get("/media/accounts")
    async def list_accounts(platform: str | None = None) -> dict[str, Any]:
        return {"items": service().store.list_accounts(platform=platform)}

    class AccountUpsert(BaseModel):
        platform: str = Field(min_length=1, max_length=32)
        external_account_id: str = Field(default="", max_length=200)
        display_name: str = Field(default="", max_length=200)
        auth_status: str = Field(default="AUTH_REQUIRED", max_length=64)
        scopes: list[str] = Field(default_factory=list)
        metadata: dict[str, Any] = Field(default_factory=dict)
        secret_ref: str = Field(default="", max_length=400)

    @router.post("/media/accounts", status_code=status.HTTP_201_CREATED)
    async def upsert_account(payload: AccountUpsert) -> dict[str, Any]:
        # Never accept raw tokens through this endpoint — secret_ref only.
        data = payload.model_dump()
        return {"account": service().store.upsert_account(data)}

    @router.post("/media/scheduler/tick")
    async def scheduler_tick() -> dict[str, Any]:
        return await service().scheduler.tick()

    return router
