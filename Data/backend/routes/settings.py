"""FastAPI routes for the Settings Control Plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.settings import SettingsControlPlane, SettingsError


class SettingsPatchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    confirm_dangerous: bool = False


class SettingPatchRequest(BaseModel):
    value: Any = None
    confirm_dangerous: bool = False
    clear_secret: bool = False


def build_settings_router(plane: SettingsControlPlane) -> APIRouter:
    router = APIRouter(tags=["settings"])

    def _raise(exc: Exception) -> None:
        if isinstance(exc, SettingsError):
            raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc
        raise

    @router.get("/api/settings")
    def get_settings() -> dict:
        return plane.public_snapshot()

    @router.get("/api/settings/catalog")
    def get_catalog() -> dict:
        return plane.catalog()

    @router.get("/api/settings/categories/{category}")
    def get_category(category: str) -> dict:
        try:
            states = plane.list_states(category=category)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise
        return {
            "category": category,
            "settings": [state.public_dict() for state in states],
        }

    @router.get("/api/settings/keys/{key:path}")
    def get_key(key: str) -> dict:
        try:
            return {"setting": plane.get_state(key).public_dict()}
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise

    @router.patch("/api/settings")
    def patch_settings(payload: SettingsPatchRequest) -> dict:
        try:
            results = plane.patch_many(
                payload.values,
                confirm_dangerous=payload.confirm_dangerous,
            )
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise
        return {
            "results": [item.public_dict() for item in results],
            "settings": [state.public_dict() for state in plane.list_states()],
        }

    @router.patch("/api/settings/keys/{key:path}")
    def patch_key(key: str, payload: SettingPatchRequest) -> dict:
        try:
            if payload.clear_secret:
                result = plane.clear_secret(key)
            else:
                results = plane.patch_many(
                    {key: payload.value},
                    confirm_dangerous=payload.confirm_dangerous,
                )
                result = results[0] if results else None
                if result is None:
                    # Empty secret keep-existing
                    return {"result": {"key": key, "status": "SAVED", "message": "Unchanged"}, "setting": plane.get_state(key).public_dict()}
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise
        return {"result": result.public_dict(), "setting": plane.get_state(key).public_dict()}

    @router.post("/api/settings/reset/{key:path}")
    def reset_key(key: str) -> dict:
        try:
            result = plane.reset_key(key)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise
        return {"result": result.public_dict(), "setting": plane.get_state(key).public_dict()}

    @router.post("/api/settings/reset-category/{category}")
    def reset_category(category: str) -> dict:
        try:
            results = plane.reset_category(category)
        except Exception as exc:  # noqa: BLE001
            _raise(exc)
            raise
        return {
            "results": [item.public_dict() for item in results],
            "settings": [state.public_dict() for state in plane.list_states(category=category)],
        }

    return router
