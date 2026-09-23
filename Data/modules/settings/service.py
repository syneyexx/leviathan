"""Settings Control Plane — catalog, persistence, validation, and consumer apply."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from Data.backend.config import Settings, _resolve_data_root, _resolve_path

from .catalog import CATALOG, CATALOG_BY_KEY, CATEGORY_BY_ID, categories_public
from .store import SettingsOverrideStore
from .types import (
    ApplyMode,
    MutationResult,
    MutationStatus,
    SettingSource,
    SettingState,
    SettingType,
    SettingsError,
)
from .validation import coerce_value, validate_feature_hierarchy

ApplyCallback = Callable[[str, Any, Settings], None]


def _read_path(settings: Settings, path: tuple[str, ...]) -> Any:
    current: Any = settings
    for part in path:
        current = getattr(current, part)
    return current


def _path_to_pathlib(definition_path: tuple[str, ...], value: Any) -> Any:
    if value is None or value == "":
        return value
    key_tail = definition_path[-1] if definition_path else ""
    if key_tail in {"data_root", "workspace", "markets_root"} or definition_path == (
        "research_integration",
        "corpus_root",
    ):
        if definition_path[-1] == "corpus_root":
            return str(value)
        return _resolve_data_root(str(value))
    if key_tail in {"root"} or definition_path == ("database_path",):
        return _resolve_path(str(value))
    return value


def apply_overrides_to_settings(base: Settings, overrides: dict[str, Any]) -> Settings:
    """Return a new Settings with catalog overrides applied (skips bootstrap-only)."""
    current = base
    # Group by top-level domain for nested replaces.
    for key, raw in overrides.items():
        definition = CATALOG_BY_KEY.get(key)
        if definition is None:
            continue
        if definition.apply_mode == ApplyMode.BOOTSTRAP_ONLY:
            continue
        if not definition.path:
            continue
        value = raw
        if definition.value_type == SettingType.STRING_LIST and isinstance(raw, list):
            value = tuple(raw)
        if definition.value_type == SettingType.PATH:
            value = _path_to_pathlib(definition.path, raw)
        if definition.value_type in {SettingType.STRING, SettingType.URL, SettingType.SECRET, SettingType.ENUM}:
            if raw == "" and definition.default is None:
                value = None
            elif definition.key == "web_search.endpoint" and raw == "":
                value = None
        current = _set_path(current, definition.path, value)
    return current


def _set_path(settings: Settings, path: tuple[str, ...], value: Any) -> Settings:
    if len(path) == 1:
        return replace(settings, **{path[0]: value})
    domain_name = path[0]
    domain = getattr(settings, domain_name)
    nested = replace(domain, **{path[1]: value}) if len(path) == 2 else domain
    if len(path) > 2:
        # Only two-level nested domains exist today.
        raise SettingsError("INVALID_PATH", f"Unsupported settings path depth: {path}")
    return replace(settings, **{domain_name: nested})


def merge_db_overrides_if_available(base: Settings) -> Settings:
    """Early boot merge: apply SQLite overrides when the table already exists."""
    path = Path(base.database_path)
    if not path.exists():
        return base
    try:
        conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='settings_overrides'"
            ).fetchone()
            if row is None:
                return base
            rows = conn.execute("SELECT key, value_json FROM settings_overrides").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return base
    import json

    overrides: dict[str, Any] = {}
    for key, value_json in rows:
        try:
            overrides[str(key)] = json.loads(value_json)
        except json.JSONDecodeError:
            continue
    if not overrides:
        return base
    try:
        return apply_overrides_to_settings(base, overrides)
    except Exception:
        return base


class SettingsControlPlane:
    """Canonical Settings Control Plane.

    Precedence for operator-adjustable keys:
      hard safety invariants (validate)
        > persisted override
        > environment / default (boot Settings)

    Bootstrap-only keys (database_path) are never overridden from SQLite.
    """

    def __init__(
        self,
        boot_settings: Settings,
        *,
        store: SettingsOverrideStore | None = None,
    ) -> None:
        self._boot = boot_settings
        self.store = store or SettingsOverrideStore(boot_settings.database_path)
        self._overrides: dict[str, Any] = {}
        self._desired: Settings = boot_settings
        self._effective: Settings = boot_settings
        self._apply_callbacks: list[ApplyCallback] = []
        self._started = False

    @property
    def boot(self) -> Settings:
        return self._boot

    @property
    def effective(self) -> Settings:
        return self._effective

    @property
    def desired(self) -> Settings:
        return self._desired

    def register_apply_callback(self, callback: ApplyCallback) -> None:
        self._apply_callbacks.append(callback)

    def start(self) -> Settings:
        self.store.ensure_schema()
        self._overrides = self.store.list_all()
        self._desired = apply_overrides_to_settings(self._boot, self._overrides)
        # Effective = boot values already merged at import via merge_db_overrides_if_available,
        # then re-apply hot values from overrides for honesty after mid-process changes.
        self._effective = apply_overrides_to_settings(self._boot, self._hot_overrides_only())
        # Restart-required keys that were present at boot are already in boot_settings
        # when merge_db_overrides_if_available ran; keep effective aligned with boot for those.
        self._effective = self._merge_restart_from_boot(self._effective)
        self._started = True
        self._run_callbacks_for_all_hot()
        return self._effective

    def _hot_overrides_only(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self._overrides.items():
            definition = CATALOG_BY_KEY.get(key)
            if definition is None:
                continue
            if definition.apply_mode in {ApplyMode.HOT, ApplyMode.SUBSYSTEM_RELOAD}:
                out[key] = value
        return out

    def _merge_restart_from_boot(self, effective: Settings) -> Settings:
        """Restart-required values take effect only when present in boot_settings."""
        current = effective
        for definition in CATALOG:
            if definition.apply_mode != ApplyMode.RESTART_REQUIRED:
                continue
            if not definition.path:
                continue
            boot_val = _read_path(self._boot, definition.path)
            current = _set_path(current, definition.path, boot_val)
        return current

    def _run_callbacks_for_all_hot(self) -> None:
        for definition in CATALOG:
            if definition.apply_mode not in {ApplyMode.HOT, ApplyMode.SUBSYSTEM_RELOAD}:
                continue
            value = _read_path(self._effective, definition.path) if definition.path else None
            for callback in self._apply_callbacks:
                callback(definition.key, value, self._effective)

    def catalog(self) -> dict[str, Any]:
        return {
            "categories": categories_public(),
            "settings": [
                {
                    "key": item.key,
                    "category": item.category,
                    "label": item.label,
                    "description": item.description,
                    "type": item.value_type.value,
                    "default": None if item.secret else self._public_default(item),
                    "secret": item.secret,
                    "editable": item.editable,
                    "dangerous": item.dangerous,
                    "apply_mode": item.apply_mode.value,
                    "requires": list(item.requires),
                    "enum_values": list(item.enum_values),
                    "min_value": item.min_value,
                    "max_value": item.max_value,
                    "consumer": item.consumer,
                    "experimental": item.experimental,
                }
                for item in CATALOG
            ],
            "precedence": [
                "hard_safety_invariants",
                "persisted_operator_override",
                "environment_or_default",
            ],
        }

    def _public_default(self, item: Any) -> Any:
        default = item.default
        if item.value_type == SettingType.STRING_LIST and isinstance(default, tuple):
            return list(default)
        if isinstance(default, Path):
            return str(default)
        return default

    def list_states(self, *, category: str | None = None) -> list[SettingState]:
        states = [self.get_state(item.key) for item in CATALOG]
        if category:
            if category not in CATEGORY_BY_ID:
                raise SettingsError("UNKNOWN_CATEGORY", f"Unknown category: {category}", http_status=404)
            states = [s for s in states if s.category == category]
        return states

    def get_state(self, key: str) -> SettingState:
        definition = CATALOG_BY_KEY.get(key)
        if definition is None:
            raise SettingsError("UNKNOWN_SETTING", f"Unknown setting: {key}", http_status=404)

        boot_value = _read_path(self._boot, definition.path) if definition.path else None
        desired_value = _read_path(self._desired, definition.path) if definition.path else None
        effective_value = _read_path(self._effective, definition.path) if definition.path else None

        if key in self._overrides:
            source = SettingSource.OVERRIDE.value
        elif definition.env_name and os.getenv(definition.env_name) is not None:
            source = SettingSource.ENVIRONMENT.value
        else:
            source = SettingSource.DEFAULT.value

        if definition.apply_mode == ApplyMode.BOOTSTRAP_ONLY or not definition.editable:
            source = SettingSource.LOCKED.value if definition.apply_mode == ApplyMode.BOOTSTRAP_ONLY else source

        restart_pending = False
        if definition.apply_mode == ApplyMode.RESTART_REQUIRED and key in self._overrides:
            if self._normalize_compare(desired_value) != self._normalize_compare(effective_value):
                restart_pending = True

        status = "effective"
        if restart_pending:
            status = "restart_required"
        elif not definition.editable:
            status = "read_only"

        configured: bool | None = None
        if definition.secret:
            secret_val = desired_value if desired_value is not None else boot_value
            if isinstance(secret_val, str):
                configured = bool(secret_val.strip()) and secret_val.strip() != "not-needed"
            else:
                configured = bool(secret_val)

        return SettingState(
            key=key,
            category=definition.category,
            label=definition.label,
            description=definition.description,
            value_type=definition.value_type.value,
            default_value=self._serialize(definition.default),
            desired_value=self._serialize(desired_value),
            effective_value=self._serialize(effective_value),
            source=source,
            editable=definition.editable and definition.apply_mode != ApplyMode.BOOTSTRAP_ONLY,
            secret=definition.secret,
            configured=configured,
            restart_required=definition.apply_mode == ApplyMode.RESTART_REQUIRED,
            apply_mode=definition.apply_mode.value,
            status=status,
            dangerous=definition.dangerous,
            experimental=definition.experimental,
            requires=list(definition.requires),
            enum_values=list(definition.enum_values),
            min_value=definition.min_value,
            max_value=definition.max_value,
            consumer=definition.consumer,
            effective_now=not restart_pending,
        )

    def _serialize(self, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, tuple):
            return list(value)
        return value

    def _normalize_compare(self, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, tuple):
            return list(value)
        return value

    def patch_many(
        self,
        updates: dict[str, Any],
        *,
        updated_by: str = "operator",
        confirm_dangerous: bool = False,
    ) -> list[MutationResult]:
        if not updates:
            return []
        unknown = [key for key in updates if key not in CATALOG_BY_KEY]
        if unknown:
            raise SettingsError("UNKNOWN_SETTING", f"Unknown setting keys: {unknown}", http_status=404)

        coerced: dict[str, Any] = {}
        for key, raw in updates.items():
            definition = CATALOG_BY_KEY[key]
            if not definition.editable or definition.apply_mode == ApplyMode.BOOTSTRAP_ONLY:
                raise SettingsError(
                    "LOCKED",
                    f"{key} is not editable (source managed / bootstrap-only)",
                    http_status=403,
                )
            if definition.dangerous and not confirm_dangerous:
                raise SettingsError(
                    "CONFIRM_REQUIRED",
                    f"{key} is security-sensitive; set confirm_dangerous=true",
                    http_status=409,
                )
            if definition.secret and (raw is None or raw == ""):
                # Empty secret means "keep existing"
                continue
            coerced[key] = coerce_value(definition, raw)

        # Build prospective desired map for hierarchy checks.
        prospective = {item.key: self.get_state(item.key).desired_value for item in CATALOG}
        for key, value in coerced.items():
            prospective[key] = self._serialize(value)
        # When enabling MCP without transports, default stdio=true (matches from_env).
        if prospective.get("features.mcp_enabled") and not prospective.get("features.mcp_stdio") and not prospective.get(
            "features.mcp_http"
        ):
            if "features.mcp_stdio" not in coerced and "features.mcp_http" not in coerced:
                coerced["features.mcp_stdio"] = True
                prospective["features.mcp_stdio"] = True
        validate_feature_hierarchy(prospective)

        # Extra Settings.validate via reconstructed object.
        trial_overrides = dict(self._overrides)
        for key, value in coerced.items():
            trial_overrides[key] = value if not isinstance(value, tuple) else list(value)
        trial = apply_overrides_to_settings(self._boot, trial_overrides)
        try:
            trial.validate()
        except Exception as exc:  # noqa: BLE001
            raise SettingsError("VALIDATION_FAILED", str(exc), http_status=422) from exc

        results: list[MutationResult] = []
        for key, value in coerced.items():
            results.append(self._commit_one(key, value, updated_by=updated_by))
        return results

    def _commit_one(self, key: str, value: Any, *, updated_by: str) -> MutationResult:
        definition = CATALOG_BY_KEY[key]
        store_value = list(value) if isinstance(value, tuple) else value
        if isinstance(store_value, Path):
            store_value = str(store_value)
        self.store.put(key, store_value, updated_by=updated_by)
        self._overrides[key] = store_value
        self._desired = apply_overrides_to_settings(self._boot, self._overrides)

        if definition.apply_mode in {ApplyMode.HOT, ApplyMode.SUBSYSTEM_RELOAD}:
            self._effective = _set_path(
                self._effective,
                definition.path,
                _path_to_pathlib(definition.path, value)
                if definition.value_type == SettingType.PATH
                else value,
            )
            for callback in self._apply_callbacks:
                callback(key, value, self._effective)
            return MutationResult(
                key=key,
                status=MutationStatus.APPLIED,
                message="Saved and applied",
                desired_value=self._serialize(value),
                effective_value=self._serialize(value),
                restart_required=False,
                saved=True,
                applied=True,
            )

        # Restart required — desired updated, effective unchanged.
        return MutationResult(
            key=key,
            status=MutationStatus.RESTART_REQUIRED,
            message="Saved — restart required for effective change",
            desired_value=self._serialize(_read_path(self._desired, definition.path)),
            effective_value=self._serialize(_read_path(self._effective, definition.path)),
            restart_required=True,
            saved=True,
            applied=False,
        )

    def reset_key(self, key: str, *, updated_by: str = "operator") -> MutationResult:
        definition = CATALOG_BY_KEY.get(key)
        if definition is None:
            raise SettingsError("UNKNOWN_SETTING", f"Unknown setting: {key}", http_status=404)
        if not definition.editable or definition.apply_mode == ApplyMode.BOOTSTRAP_ONLY:
            raise SettingsError("LOCKED", f"{key} cannot be reset", http_status=403)
        if definition.secret:
            raise SettingsError(
                "SECRET_RESET_BLOCKED",
                f"{key} is a secret — clear explicitly via PATCH with clear_secret",
                http_status=409,
            )
        existed = self.store.delete(key)
        self._overrides.pop(key, None)
        self._desired = apply_overrides_to_settings(self._boot, self._overrides)
        boot_value = _read_path(self._boot, definition.path)
        if definition.apply_mode in {ApplyMode.HOT, ApplyMode.SUBSYSTEM_RELOAD}:
            self._effective = _set_path(self._effective, definition.path, boot_value)
            for callback in self._apply_callbacks:
                callback(key, boot_value, self._effective)
            status = MutationStatus.APPLIED if existed else MutationStatus.RESET
            return MutationResult(
                key=key,
                status=status,
                message="Reset to environment/default and applied",
                desired_value=self._serialize(boot_value),
                effective_value=self._serialize(boot_value),
                saved=True,
                applied=True,
            )
        return MutationResult(
            key=key,
            status=MutationStatus.RESTART_REQUIRED if existed else MutationStatus.RESET,
            message="Reset persisted — restart may be required",
            desired_value=self._serialize(boot_value),
            effective_value=self._serialize(_read_path(self._effective, definition.path)),
            restart_required=definition.apply_mode == ApplyMode.RESTART_REQUIRED,
            saved=True,
            applied=False,
        )

    def reset_category(self, category: str, *, updated_by: str = "operator") -> list[MutationResult]:
        if category not in CATEGORY_BY_ID:
            raise SettingsError("UNKNOWN_CATEGORY", f"Unknown category: {category}", http_status=404)
        results: list[MutationResult] = []
        for item in CATALOG:
            if item.category != category:
                continue
            if not item.editable or item.apply_mode == ApplyMode.BOOTSTRAP_ONLY or item.secret:
                continue
            if item.key not in self._overrides:
                continue
            results.append(self.reset_key(item.key, updated_by=updated_by))
        return results

    def clear_secret(self, key: str, *, updated_by: str = "operator") -> MutationResult:
        definition = CATALOG_BY_KEY.get(key)
        if definition is None or not definition.secret:
            raise SettingsError("NOT_SECRET", f"{key} is not a secret setting", http_status=400)
        empty = ""
        self.store.put(key, empty, updated_by=updated_by)
        self._overrides[key] = empty
        self._desired = apply_overrides_to_settings(self._boot, self._overrides)
        if definition.apply_mode in {ApplyMode.HOT, ApplyMode.SUBSYSTEM_RELOAD}:
            self._effective = _set_path(self._effective, definition.path, empty)
            for callback in self._apply_callbacks:
                callback(key, empty, self._effective)
        return MutationResult(
            key=key,
            status=MutationStatus.APPLIED,
            message="Secret cleared",
            desired_value=None,
            effective_value=None,
            saved=True,
            applied=True,
        )

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "categories": categories_public(),
            "settings": [state.public_dict() for state in self.list_states()],
            "effective_summary": self._effective.public_summary(),
        }
