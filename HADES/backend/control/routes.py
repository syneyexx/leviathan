"""FastAPI routes for the HADES Control Center."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .presets import list_presets
from .service import get_control_service
from .types import ResolveContext
from .validation import SettingValidationError


router = APIRouter(prefix="/api/control", tags=["control"])


class ScopeContextInput(BaseModel):
    project_id: str | None = None
    agent_type: str | None = None
    agent_id: str | None = None
    plugin_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    model_id: str | None = None
    provider: str | None = None


class PatchSettingsInput(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = None


class OverrideInput(BaseModel):
    setting_id: str = Field(min_length=1)
    value: Any = None
    scope: Literal["global", "project", "agent_type", "agent", "plugin", "session", "task"] = "global"
    scope_id: str | None = None


class DeleteOverrideInput(BaseModel):
    setting_id: str = Field(min_length=1)
    scope: Literal["global", "project", "agent_type", "agent", "plugin", "session", "task"] = "global"
    scope_id: str | None = None


class PresetInput(BaseModel):
    preset_id: str = Field(min_length=1)


class ImportInput(BaseModel):
    config_schema_version: int | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    overrides: list[dict[str, Any]] = Field(default_factory=list)


class ExplainStopInput(BaseModel):
    constraint_id: str = Field(min_length=1)
    current: Any = None
    enforced_by: str = Field(default="manual")
    message: str | None = None
    context: ScopeContextInput | None = None


def _ctx(data: ScopeContextInput | None) -> ResolveContext:
    if not data:
        return ResolveContext()
    return ResolveContext(**data.model_dump())


@router.get("/dashboard")
async def control_dashboard() -> dict[str, Any]:
    return get_control_service().dashboard()


@router.get("/definitions")
async def control_definitions(category: str | None = None, q: str | None = None) -> dict[str, Any]:
    service = get_control_service()
    return {"definitions": service.definitions(category=category, q=q), "categories": service.registry.categories()}


@router.get("/values")
async def control_values() -> dict[str, Any]:
    service = get_control_service()
    return {"values": service.global_values(), "cache_version": service.cache_version}


@router.get("/effective")
async def control_effective(
    project_id: str | None = None,
    agent_type: str | None = None,
    agent_id: str | None = None,
    plugin_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    setting_id: str | None = None,
) -> dict[str, Any]:
    service = get_control_service()
    context = ResolveContext(
        project_id=project_id,
        agent_type=agent_type,
        agent_id=agent_id,
        plugin_id=plugin_id,
        session_id=session_id,
        task_id=task_id,
    )
    if setting_id:
        return {"effective": service.resolve(setting_id, context).to_public()}
    return {"effective": service.effective_map(context)}


@router.patch("/settings")
async def control_patch_settings(body: PatchSettingsInput) -> dict[str, Any]:
    service = get_control_service()
    current = service.global_values()
    current_rev = int(current.get("config_revision") or 0)
    if body.expected_revision is not None and int(body.expected_revision) != current_rev:
        raise HTTPException(
            status_code=409,
            detail={
                "conflict": True,
                "message": "Settings conflict: another editor saved newer changes.",
                "current_revision": current_rev,
                "expected_revision": int(body.expected_revision),
                "values": current,
            },
        )
    try:
        saved = service.patch_global(body.values)
    except SettingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    side_effects = _apply_runtime_side_effects(service)
    return {
        "values": saved,
        "cache_version": service.cache_version,
        "config_revision": int(saved.get("config_revision") or 0),
        "side_effects": side_effects,
    }


@router.put("/override")
async def control_set_override(body: OverrideInput) -> dict[str, Any]:
    service = get_control_service()
    try:
        result = service.set_override(body.setting_id, body.value, scope=body.scope, scope_id=body.scope_id)
    except (SettingValidationError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    side_effects = _apply_runtime_side_effects(service)
    if isinstance(result, dict):
        result = {**result, "side_effects": side_effects}
    return result


@router.post("/override/delete")
async def control_delete_override(body: DeleteOverrideInput) -> dict[str, Any]:
    service = get_control_service()
    try:
        result = service.delete_override(body.setting_id, scope=body.scope, scope_id=body.scope_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    side_effects = _apply_runtime_side_effects(service)
    if isinstance(result, dict):
        result = {**result, "side_effects": side_effects}
    return result


@router.get("/scopes")
async def control_scopes() -> dict[str, Any]:
    return {
        "scopes": ["system", "global", "project", "agent_type", "agent", "plugin", "session", "task"],
        "precedence": ["system", "global", "project", "agent_type", "agent", "plugin", "session", "task"],
    }


@router.get("/capabilities")
async def control_capabilities() -> dict[str, Any]:
    return {"capabilities": get_control_service().capabilities.public()}


@router.get("/immutable")
async def control_immutable() -> dict[str, Any]:
    from .immutable import public_immutable

    return {"constraints": public_immutable()}


@router.get("/history")
async def control_history(key: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"history": get_control_service().history(key=key, limit=limit)}


@router.get("/presets")
async def control_presets() -> dict[str, Any]:
    return {"presets": list_presets()}


@router.post("/presets/apply")
async def control_apply_preset(body: PresetInput) -> dict[str, Any]:
    service = get_control_service()
    try:
        result = service.apply_preset(body.preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    side_effects = _apply_runtime_side_effects(service)
    if isinstance(result, dict):
        result = {**result, "side_effects": side_effects}
    return result


@router.post("/export")
async def control_export(include_secrets: bool = False) -> dict[str, Any]:
    return get_control_service().export_config(include_secrets=include_secrets)


@router.post("/import")
async def control_import(body: ImportInput) -> dict[str, Any]:
    service = get_control_service()
    try:
        result = service.import_config(body.model_dump())
    except SettingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    side_effects = _apply_runtime_side_effects(service)
    if isinstance(result, dict):
        result = {**result, "side_effects": side_effects}
    return result


@router.post("/reset/category/{category}")
async def control_reset_category(category: str) -> dict[str, Any]:
    service = get_control_service()
    result = service.reset_category(category)
    side_effects = _apply_runtime_side_effects(service)
    if isinstance(result, dict):
        result = {**result, "side_effects": side_effects}
    return result


@router.post("/reset")
async def control_reset_all() -> dict[str, Any]:
    service = get_control_service()
    values = service.reset_all()
    side_effects = _apply_runtime_side_effects(service)
    return {"values": values, "side_effects": side_effects}


@router.get("/limits")
async def control_limits(limit: int = 50) -> dict[str, Any]:
    return {"events": get_control_service().recent_limit_events(limit)}


@router.post("/limits/explain")
async def control_explain_stop(body: ExplainStopInput) -> dict[str, Any]:
    service = get_control_service()
    try:
        return {
            "event": service.explain_stop(
                body.constraint_id,
                current=body.current,
                enforced_by=body.enforced_by,
                context=_ctx(body.context),
                message=body.message,
            )
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _apply_runtime_side_effects(service: Any) -> dict[str, Any]:
    """Push concurrency / shared budget into live runtime objects when available.

    Returns honesty metadata so callers do not claim silent success when apply fails.
    """
    errors: list[str] = []
    applied: list[str] = []
    try:
        from reasoning.atomic_budget import shared_budget_pool

        shared_budget_pool.configure(service.shared_budget_config())
        applied.append("shared_budget")
    except Exception as exc:  # noqa: BLE001 - surface side-effect failures
        errors.append(f"shared_budget:{exc}")
    try:
        import main as main_mod

        values = service.global_values()
        concurrency = values.get("max_concurrent_tasks")
        if concurrency is not None and getattr(main_mod, "runner", None) is not None:
            main_mod.runner.set_concurrency(int(concurrency))
            applied.append("max_concurrent_tasks")
    except Exception as exc:  # noqa: BLE001 - surface side-effect failures
        errors.append(f"max_concurrent_tasks:{exc}")
    return {"ok": not errors, "applied": applied, "errors": errors}
