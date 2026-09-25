"""FastAPI routes for the Settings Control Plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from Data.modules.settings import SettingsControlPlane, SettingsError


class SettingsPatchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    confirm_dangerous: bool = False


class SettingPatchRequest(BaseModel):
    value: Any = None
    confirm_dangerous: bool = False
    clear_secret: bool = False


class BehaviorPromptPatch(BaseModel):
    system_prompt: str = Field(..., min_length=1, max_length=200_000)


class BehaviorProfilePatch(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class BehaviorPreviewRequest(BaseModel):
    latest_user_message: str = ""
    recent_user_messages: list[str] = Field(default_factory=list)


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
                    return {
                        "result": {"key": key, "status": "SAVED", "message": "Unchanged"},
                        "setting": plane.get_state(key).public_dict(),
                    }
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


def build_behavior_router(behavior_store: Any, observability: Any | None = None) -> APIRouter:
    """BehaviorProfile routes — behavior is not authority.

    Models are defined at module scope so FastAPI treats them as JSON bodies.
    Nested local classes were incorrectly bound as required query params,
    producing opaque ``Field required`` / ``query.payload`` 422s.

    Mutations persist to BehaviorProfileStore and invalidate effective-behavior
    caches via store.on_change listeners. Hot-apply: next independent turn
    resolves the new profile — no restart, refresh, or new chat required.
    """

    router = APIRouter(tags=["settings", "behavior"])

    def _emit_behavior_updated(
        *,
        old_hash: str | None,
        profile: Any,
        updated_by: str,
        changed_fields: list[str],
    ) -> None:
        if observability is None:
            return
        try:
            observability.emit(
                "settings",
                "behavior.updated",
                payload={
                    "profile_id": getattr(profile, "id", None),
                    "old_hash": old_hash,
                    "new_hash": getattr(profile, "hash", None),
                    "version": str(getattr(profile, "version", "") or ""),
                    "updated_by": updated_by,
                    "changed_fields": list(changed_fields),
                    # Never include full system_prompt contents.
                },
            )
        except Exception:  # noqa: BLE001
            pass

    @router.get("/api/settings/behavior-profile")
    def get_behavior_profile() -> dict:
        return {
            "profile": behavior_store.public_effective(include_prompt=True),
            "truth": {
                "behavior_is_not_authority": True,
                "system_prompt_is_not_capability_grant": True,
                "does_not_bypass_execution_gateway": True,
                "does_not_bypass_approvals": True,
                "settings_are_sole_identity_authority": True,
                "hot_applies_next_turn": True,
            },
        }

    @router.put("/api/settings/behavior-profile/system-prompt")
    def put_system_prompt(payload: BehaviorPromptPatch = Body(...)) -> dict:
        prior = behavior_store.get_effective()
        old_hash = prior.hash or prior.compute_hash()
        profile = behavior_store.update_system_prompt(payload.system_prompt)
        _emit_behavior_updated(
            old_hash=old_hash,
            profile=profile,
            updated_by="operator",
            changed_fields=["system_prompt"],
        )
        effective = behavior_store.public_effective(include_prompt=True)
        return {
            "profile": profile.public_dict(include_prompt=True),
            "effective": effective,
            "hash": profile.hash,
            "version": profile.version,
            "updated_at": effective.get("updated_at"),
            "truth": {
                "behavior_is_not_authority": True,
                "permissions_unchanged": True,
                "applies_without_restart": True,
                "hot_applies_next_turn": True,
            },
        }

    @router.patch("/api/settings/behavior-profile")
    def patch_behavior_profile(payload: BehaviorProfilePatch = Body(...)) -> dict:
        if not isinstance(payload.values, dict):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Behavior update body missing `values`",
                    "expected": {"values": {"system_prompt": "...", "...": "..."}},
                },
            )
        prior = behavior_store.get_effective()
        old_hash = prior.hash or prior.compute_hash()
        try:
            profile = behavior_store.patch(payload.values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        _emit_behavior_updated(
            old_hash=old_hash,
            profile=profile,
            updated_by="operator",
            changed_fields=sorted(str(k) for k in payload.values.keys()),
        )
        effective = behavior_store.public_effective(include_prompt=True)
        return {
            "profile": profile.public_dict(include_prompt=True),
            "effective": effective,
            "hash": profile.hash,
            "version": profile.version,
            "updated_at": effective.get("updated_at"),
            "truth": {
                "behavior_is_not_authority": True,
                "permissions_unchanged": True,
                "applies_without_restart": True,
                "hot_applies_next_turn": True,
            },
        }

    @router.post("/api/settings/behavior-profile/reset")
    def reset_behavior_profile() -> dict:
        prior = behavior_store.get_effective()
        old_hash = prior.hash or prior.compute_hash()
        profile = behavior_store.reset_to_default()
        _emit_behavior_updated(
            old_hash=old_hash,
            profile=profile,
            updated_by="operator:reset",
            changed_fields=["reset"],
        )
        effective = behavior_store.public_effective(include_prompt=True)
        return {
            "profile": profile.public_dict(include_prompt=True),
            "effective": effective,
            "hash": profile.hash,
            "version": profile.version,
            "updated_at": effective.get("updated_at"),
        }

    @router.post("/api/settings/behavior-profile/preview")
    def preview_behavior(payload: BehaviorPreviewRequest = Body(...)) -> dict:
        """Safe preview of language decision + public behavior metadata (no secrets)."""
        from Data.modules.settings.resolver import BehaviorSettingsResolver, snapshot_hash

        resolver = BehaviorSettingsResolver(behavior_store)
        snap = resolver.resolve(
            latest_user_message=payload.latest_user_message,
            recent_user_messages=list(payload.recent_user_messages or []),
        )
        prompt = snap.system_prompt or ""
        digest = __import__("hashlib").sha256(prompt.encode("utf-8")).hexdigest()
        return {
            "language": snap.language.public_dict(),
            "behavior": snap.public_dict(include_prompt=False),
            "system_prompt_digest": digest,
            "system_prompt_chars": len(prompt),
            "snapshot_hash": snapshot_hash(snap),
            "truth": {
                "preview_does_not_mutate_settings": True,
                "full_system_prompt_not_returned_by_default": True,
            },
        }

    return router
