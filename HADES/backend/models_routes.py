"""Models / gateway HTTP routes — shared capacity surface (work package L / H)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from database import DEFAULT_PROFILE
from dataset_brain_routes import mount_dataset_brain_routes
from training_routes import mount_training_routes

router = APIRouter(tags=["models"])

# Storage/API ceiling only. The effective usable prompt remains bounded by the
# loaded model/provider context window and is checked before inference.
MAX_SYSTEM_PROMPT_CHARS = 500_000


class ModelProfileInput(BaseModel):
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.95, gt=0, le=1)
    top_k: int = Field(default=40, ge=0, le=500)
    max_tokens: int = Field(default=2048, ge=1, le=131_072)
    repeat_penalty: float = Field(default=1.05, ge=0.5, le=2)
    seed: int = Field(default=-1, ge=-1, le=2_147_483_647)
    system_prompt: str = Field(default=DEFAULT_PROFILE["system_prompt"], max_length=MAX_SYSTEM_PROMPT_CHARS)
    make_active: bool = True


class ModelsGatewayResponse(BaseModel):
    """Explicit gateway overview response for OpenAPI / TS contracts."""

    gateway: dict[str, Any]
    router_capacity: dict[str, Any]
    budget_pool: dict[str, Any] | None = None


class ModelsListResponse(BaseModel):
    connected: bool
    models: list[dict[str, Any]]
    active_profile: dict[str, Any]
    latency_ms: float | int | None = None
    error: str | None = None
    gateway: dict[str, Any] | None = None
    router_capacity: dict[str, Any] | None = None


def mount_models_routes(ctx: dict[str, Any]) -> APIRouter:
    class _Svc:
        def __getattr__(self, name: str) -> Any:
            return ctx[name]

        def get(self, name: str, default: Any = None) -> Any:
            return ctx.get(name, default)

    s = _Svc()

    @router.get("/models", response_model=ModelsListResponse, response_model_exclude_unset=False)
    async def list_models() -> dict[str, Any]:
        from lm_studio import LmStudioError

        try:
            models, latency = await s.discover_models()
            s.sync_model_gateway_from_settings()
            return {
                "connected": True,
                "models": models,
                "active_profile": s.database.active_profile(),
                "latency_ms": latency,
                "gateway": s.model_gateway.overview(),
                "router_capacity": s.model_router.capacity_overview(),
            }
        except LmStudioError as exc:
            return {
                "connected": False,
                "models": [],
                "active_profile": s.database.active_profile(),
                "error": str(exc),
                "gateway": s.model_gateway.overview(),
                "router_capacity": s.model_router.capacity_overview(),
            }

    @router.get("/models/gateway", response_model=ModelsGatewayResponse)
    async def models_gateway_overview() -> dict[str, Any]:
        s.sync_model_gateway_from_settings()
        return {
            "gateway": s.model_gateway.overview(),
            "router_capacity": s.model_router.capacity_overview(),
            "budget_pool": s.shared_budget_pool.snapshot(),
        }

    @router.get("/models/{model_id:path}/profile")
    async def get_model_profile(model_id: str) -> dict[str, Any]:
        return s.database.profile_for(model_id)

    @router.put("/models/{model_id:path}/profile")
    async def save_model_profile(model_id: str, values: ModelProfileInput) -> dict[str, Any]:
        result = s.database.save_profile(
            model_id,
            values.model_dump(exclude={"make_active"}),
            make_active=values.make_active,
        )
        if values.make_active:
            try:
                from reasoning.tool_capability import tool_capability_cache

                tool_capability_cache.invalidate(model_id=model_id)
            except Exception:
                pass
        return result

    router.include_router(mount_training_routes(ctx))
    router.include_router(mount_dataset_brain_routes(ctx))
    return router
