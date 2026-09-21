"""Central HADES Control Service — authoritative config + cache + persistence."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .capabilities import CapabilityRegistry, default_capabilities
from .definitions import create_default_registry
from .events import control_events
from .immutable import public_immutable
from .presets import list_presets, preset_values
from .registry import SettingRegistry
from .resolver import PolicyResolver
from .types import (
    CONFIG_SCHEMA_VERSION,
    EffectiveValue,
    LimitEvent,
    ResolveContext,
    SettingScope,
)
from .validation import SettingValidationError, validate_value
from settings_secrets import (
    SECRET_SETTING_KEYS,
    SECRET_MASK,
    apply_secret_patches,
    is_noop_secret_patch,
    is_secret_setting_key,
    mask_settings_values,
    migrate_provider_settings_secrets,
    redact_history_value,
    resolve_settings_secrets,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Authoritative core provider secret keys for export/import masking.
# Keep aligned with settings_secrets.SECRET_SETTING_KEYS and workspace_backup.
SECRET_STORAGE_KEYS = set(SECRET_SETTING_KEYS)


class ControlService:
    """Single source of truth for HADES-owned behavioral configuration."""

    def __init__(self, database: Any, platform_db: Any | None = None) -> None:
        self.database = database
        self.platform_db = platform_db
        self.registry: SettingRegistry = create_default_registry()
        self.capabilities: CapabilityRegistry = default_capabilities()
        self._lock = threading.RLock()
        self._cache_version = 0
        self._cached_globals: dict[str, Any] | None = None
        self._cached_overrides: list[dict[str, Any]] | None = None
        self._resolver: PolicyResolver | None = None
        self._limit_events: list[LimitEvent] = []
        self.ensure_schema()
        self._rebuild_resolver()

    # ── schema / persistence ────────────────────────────────────────────────

    def ensure_schema(self) -> None:
        with self.database.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS setting_overrides (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_setting_overrides_key ON setting_overrides(key);
                CREATE INDEX IF NOT EXISTS idx_setting_overrides_scope ON setting_overrides(scope, scope_id);

                CREATE TABLE IF NOT EXISTS setting_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    actor TEXT,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_setting_history_key ON setting_history(key);

                CREATE TABLE IF NOT EXISTS config_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS limit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )
            row = db.execute("SELECT value FROM config_meta WHERE key = ?", ("config_schema_version",)).fetchone()
            if not row:
                db.execute(
                    "INSERT INTO config_meta(key, value) VALUES (?, ?)",
                    ("config_schema_version", json.dumps(CONFIG_SCHEMA_VERSION)),
                )
            else:
                version = json.loads(row["value"])
                if int(version) < CONFIG_SCHEMA_VERSION:
                    self._migrate_schema(db, int(version), CONFIG_SCHEMA_VERSION)
                    db.execute(
                        "INSERT INTO config_meta(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        ("config_schema_version", json.dumps(CONFIG_SCHEMA_VERSION)),
                    )

        # Ensure all registry defaults exist as allowed keys in DEFAULT_SETTINGS merge path.
        defaults = self.registry.defaults_map()
        from database import DEFAULT_SETTINGS

        for key, value in defaults.items():
            DEFAULT_SETTINGS.setdefault(key, value)

        migrate_provider_settings_secrets(self.database)

    def _migrate_schema(self, db: Any, from_version: int, to_version: int) -> None:
        # Placeholder for forward migrations; v1 is the initial schema.
        _ = (db, from_version, to_version)

    def schema_version(self) -> int:
        with self.database.connection() as db:
            row = db.execute("SELECT value FROM config_meta WHERE key = ?", ("config_schema_version",)).fetchone()
        return int(json.loads(row["value"])) if row else CONFIG_SCHEMA_VERSION

    # ── cache ───────────────────────────────────────────────────────────────

    def _load_globals(self) -> dict[str, Any]:
        values = self.database.get_settings()
        # Fill any missing registry keys with defaults (new installs / upgrades).
        for key, default in self.registry.defaults_map().items():
            values.setdefault(key, default)
        return values

    def _load_overrides(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT id, key, scope, scope_id, value, updated_at FROM setting_overrides ORDER BY updated_at ASC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "key": row["key"],
                "scope": row["scope"],
                "scope_id": row["scope_id"],
                "value": json.loads(row["value"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def _rebuild_resolver(self) -> None:
        with self._lock:
            self._cached_globals = self._load_globals()
            self._cached_overrides = self._load_overrides()
            self._resolver = PolicyResolver(
                self.registry,
                global_values=self._cached_globals,
                overrides=self._cached_overrides,
                capabilities=self.capabilities.as_dict(),
            )
            self._cache_version += 1

    def invalidate(self) -> None:
        self._rebuild_resolver()
        control_events.emit("settings.changed", {"cache_version": self._cache_version})

    @property
    def cache_version(self) -> int:
        return self._cache_version

    def resolver(self) -> PolicyResolver:
        with self._lock:
            if self._resolver is None:
                self._rebuild_resolver()
            assert self._resolver is not None
            return self._resolver

    # ── resolve API ─────────────────────────────────────────────────────────

    def resolve(self, setting_id: str, context: ResolveContext | None = None) -> EffectiveValue:
        return self.resolver().resolve(setting_id, context)

    def get(self, setting_id: str, context: ResolveContext | None = None, default: Any = None) -> Any:
        return self.resolver().get(setting_id, context, default=default)

    def global_values(self, *, include_secrets: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._cached_globals is None:
                self._rebuild_resolver()
            assert self._cached_globals is not None
            values = dict(self._cached_globals)
        if include_secrets:
            return resolve_settings_secrets(values)
        return mask_settings_values(values)

    def runtime_values(self) -> dict[str, Any]:
        """Internal resolved settings including keyring-backed provider secrets."""
        return self.global_values(include_secrets=True)

    # ── mutations ───────────────────────────────────────────────────────────

    def _record_history(
        self,
        key: str,
        old_value: Any,
        new_value: Any,
        scope: str,
        scope_id: str | None,
        actor: str | None,
    ) -> None:
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO setting_history(key, old_value, new_value, scope, scope_id, actor, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    json.dumps(redact_history_value(key, old_value)),
                    json.dumps(redact_history_value(key, new_value)),
                    scope,
                    scope_id,
                    actor or "user",
                    _utc_now(),
                ),
            )

    def patch_global(self, values: dict[str, Any], *, actor: str | None = "user") -> dict[str, Any]:
        """Validate and persist global overrides into app_settings."""
        current = self.global_values(include_secrets=True)
        validated: dict[str, Any] = {}
        for raw_key, raw_value in values.items():
            if raw_key in {"values", "storage", "version", "knowledge", "restart_required", "applies"}:
                continue
            definition = self.registry.get(raw_key)
            if not definition:
                # Allow unknown legacy keys that already exist in DEFAULT_SETTINGS.
                from database import DEFAULT_SETTINGS

                if raw_key in DEFAULT_SETTINGS:
                    if is_secret_setting_key(raw_key) and is_noop_secret_patch(raw_value):
                        continue
                    validated[raw_key] = raw_value
                    continue
                raise SettingValidationError(raw_key, "unknown setting")
            if not definition.overrideable:
                raise SettingValidationError(definition.id, "setting is not overrideable")
            storage_key = definition.storage_key
            if is_secret_setting_key(storage_key) and is_noop_secret_patch(raw_value):
                continue
            coerced = validate_value(definition, raw_value)
            validated[storage_key] = coerced
            old = current.get(storage_key, definition.default_value)
            if old != coerced:
                self._record_history(storage_key, old, coerced, SettingScope.GLOBAL.value, None, actor)

        validated = apply_secret_patches(current, validated)
        saved = self.database.update_settings(validated)
        self.invalidate()
        control_events.emit("policy.changed", {"scope": "global", "keys": list(validated.keys())})
        return mask_settings_values(saved)

    def set_override(
        self,
        setting_id: str,
        value: Any,
        *,
        scope: str,
        scope_id: str | None = None,
        actor: str | None = "user",
    ) -> dict[str, Any]:
        definition = self.registry.require(setting_id)
        if scope not in {s.value for s in definition.scopes} and scope != SettingScope.GLOBAL.value:
            raise SettingValidationError(definition.id, f"scope {scope} not supported")
        if scope == SettingScope.GLOBAL.value:
            return {"values": self.patch_global({definition.storage_key: value}, actor=actor)}

        coerced = validate_value(definition, value)
        from database import new_id

        if is_secret_setting_key(definition.storage_key):
            if is_noop_secret_patch(coerced):
                raise SettingValidationError(definition.id, "secret value required or omit key")
            coerced = apply_secret_patches({}, {definition.storage_key: coerced}, scope=scope, scope_id=scope_id)[
                definition.storage_key
            ]

        override_id = new_id("ovr")
        now = _utc_now()
        old = None
        with self.database.connection() as db:
            existing = db.execute(
                "SELECT id, value FROM setting_overrides WHERE key = ? AND scope = ? AND IFNULL(scope_id,'') = IFNULL(?, '')",
                (definition.storage_key, scope, scope_id),
            ).fetchone()
            if existing:
                old = json.loads(existing["value"])
                db.execute(
                    "UPDATE setting_overrides SET value = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(coerced), now, existing["id"]),
                )
                override_id = existing["id"]
            else:
                db.execute(
                    "INSERT INTO setting_overrides(id, key, scope, scope_id, value, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (override_id, definition.storage_key, scope, scope_id, json.dumps(coerced), now),
                )
        self._record_history(definition.storage_key, old, coerced, scope, scope_id, actor)
        self.invalidate()
        control_events.emit(
            "policy.changed",
            {"scope": scope, "scope_id": scope_id, "key": definition.storage_key},
        )
        return {
            "id": override_id,
            "key": definition.storage_key,
            "setting_id": definition.id,
            "scope": scope,
            "scope_id": scope_id,
            "value": coerced,
            "updated_at": now,
        }

    def delete_override(self, setting_id: str, *, scope: str, scope_id: str | None = None, actor: str | None = "user") -> dict[str, Any]:
        definition = self.registry.require(setting_id)
        if scope == SettingScope.GLOBAL.value:
            # Reset global key to default by writing default.
            return {"values": self.patch_global({definition.storage_key: definition.default_value}, actor=actor)}

        with self.database.connection() as db:
            existing = db.execute(
                "SELECT id, value FROM setting_overrides WHERE key = ? AND scope = ? AND IFNULL(scope_id,'') = IFNULL(?, '')",
                (definition.storage_key, scope, scope_id),
            ).fetchone()
            if not existing:
                return {"deleted": False}
            old = json.loads(existing["value"])
            db.execute("DELETE FROM setting_overrides WHERE id = ?", (existing["id"],))
        self._record_history(definition.storage_key, old, definition.default_value, scope, scope_id, actor)
        self.invalidate()
        control_events.emit("policy.changed", {"scope": scope, "scope_id": scope_id, "key": definition.storage_key, "deleted": True})
        return {"deleted": True, "key": definition.storage_key}

    def reset_category(self, category: str, *, actor: str | None = "user") -> dict[str, Any]:
        payload = {d.storage_key: d.default_value for d in self.registry.by_category(category)}
        return {"values": self.patch_global(payload, actor=actor), "reset_keys": list(payload.keys())}

    def reset_all(self, *, actor: str | None = "user") -> dict[str, Any]:
        with self.database.connection() as db:
            db.execute("DELETE FROM setting_overrides")
        saved = self.database.reset_settings()
        # Re-seed registry defaults that may not have been in the old DEFAULT_SETTINGS set.
        extras = {k: v for k, v in self.registry.defaults_map().items() if k not in saved}
        if extras:
            saved = self.database.update_settings(extras)
        self.invalidate()
        control_events.emit("settings.changed", {"reset": True, "actor": actor})
        return saved

    def apply_preset(self, preset_id: str, *, actor: str | None = "user") -> dict[str, Any]:
        values = preset_values(preset_id)
        if not values:
            return {"values": self.global_values(), "preset": preset_id, "applied_keys": []}
        immediate: dict[str, Any] = {}
        next_task: dict[str, Any] = {}
        restart_required: dict[str, Any] = {}
        for storage_key, raw in values.items():
            definition = self.registry.get(storage_key)
            mode = definition.apply_mode.value if definition else "immediate"
            if mode in {"restart_required", "restart"}:
                restart_required[storage_key] = raw
            elif mode == "next_task":
                next_task[storage_key] = raw
            else:
                immediate[storage_key] = raw
        to_apply = {**immediate, **next_task, **restart_required}
        saved = self.patch_global(to_apply, actor=actor)
        control_events.emit(
            "policy.changed",
            {
                "preset": preset_id,
                "immediate": list(immediate.keys()),
                "next_task": list(next_task.keys()),
                "restart_required": list(restart_required.keys()),
            },
        )
        return {
            "values": saved,
            "preset": preset_id,
            "applied_keys": list(to_apply.keys()),
            "apply_modes": {
                "immediate": list(immediate.keys()),
                "next_task": list(next_task.keys()),
                "restart_required": list(restart_required.keys()),
            },
            "config_version": self._cache_version,
            "run_config_snapshot": self.run_config_snapshot(keys=list(to_apply.keys())),
        }

    def run_config_snapshot(
        self,
        *,
        keys: list[str] | None = None,
        context: ResolveContext | None = None,
    ) -> dict[str, Any]:
        """Capture effective values + apply_mode for a run (honest config provenance)."""
        ctx = context or ResolveContext()
        selected = keys or [d.storage_key for d in self.registry.all()]
        entries: list[dict[str, Any]] = []
        for storage_key in selected:
            definition = self.registry.get(storage_key)
            if not definition:
                continue
            effective = self.resolve(definition.id, ctx)
            entries.append(
                {
                    "setting_id": definition.id,
                    "storage_key": definition.storage_key,
                    "configured": effective.configured,
                    "effective": effective.effective,
                    "source": effective.source.value if hasattr(effective.source, "value") else str(effective.source),
                    "scope": effective.scope.value if hasattr(effective.scope, "value") else str(effective.scope),
                    "apply_mode": definition.apply_mode.value,
                    "unlimited": effective.effective is None and definition.allow_unlimited,
                }
            )
        return {
            "config_version": self._cache_version,
            "captured_at": _utc_now(),
            "entry_count": len(entries),
            "entries": entries,
        }

    # ── export / import ─────────────────────────────────────────────────────

    def export_config(self, *, include_secrets: bool = False) -> dict[str, Any]:
        values = self.global_values()
        if not include_secrets:
            values = {k: ("***" if k in SECRET_STORAGE_KEYS else v) for k, v in values.items()}
        return {
            "config_schema_version": self.schema_version(),
            "exported_at": _utc_now(),
            "values": values,
            "overrides": self._load_overrides(),
            "preset_hint": values.get("autonomy_level"),
        }

    def import_config(self, payload: dict[str, Any], *, actor: str | None = "user") -> dict[str, Any]:
        version = int(payload.get("config_schema_version") or CONFIG_SCHEMA_VERSION)
        if version > CONFIG_SCHEMA_VERSION:
            raise SettingValidationError("config_schema_version", f"unsupported future schema version {version}")
        values = dict(payload.get("values") or {})
        for secret in SECRET_STORAGE_KEYS:
            if values.get(secret) == "***":
                values.pop(secret, None)
        saved = self.patch_global(values, actor=actor)
        overrides = list(payload.get("overrides") or [])
        applied_overrides = 0
        failed_overrides: list[dict[str, Any]] = []
        for row in overrides:
            key = str(row.get("key") or row.get("setting_id") or "")
            try:
                self.set_override(
                    key,
                    row.get("value"),
                    scope=str(row.get("scope")),
                    scope_id=row.get("scope_id"),
                    actor=actor,
                )
                applied_overrides += 1
            except Exception as exc:
                failed_overrides.append(
                    {
                        "key": key,
                        "scope": str(row.get("scope") or ""),
                        "scope_id": row.get("scope_id"),
                        "error": str(exc),
                    }
                )
        if failed_overrides:
            preview = "; ".join(
                f"{item.get('key') or '?'}: {item.get('error')}" for item in failed_overrides[:5]
            )
            raise SettingValidationError(
                "overrides",
                f"{len(failed_overrides)} override(s) failed ({applied_overrides} applied): {preview}",
            )
        return {
            "ok": True,
            "values": saved,
            "imported_overrides": applied_overrides,
            "requested_overrides": len(overrides),
            "failed_overrides": failed_overrides,
        }

    # ── limit inspector ─────────────────────────────────────────────────────

    def record_limit_event(self, event: LimitEvent) -> LimitEvent:
        if not event.timestamp:
            event.timestamp = _utc_now()
        with self._lock:
            self._limit_events.append(event)
            self._limit_events = self._limit_events[-200:]
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO limit_events(payload, timestamp) VALUES (?, ?)",
                (json.dumps(event.to_public()), event.timestamp),
            )
        control_events.emit("limit.hit", event.to_public())
        return event

    def recent_limit_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT payload FROM limit_events ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def explain_stop(
        self,
        constraint_id: str,
        *,
        current: Any,
        enforced_by: str,
        context: ResolveContext | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        effective = self.resolve(constraint_id, context)
        event = LimitEvent(
            constraint_id=constraint_id,
            configured=effective.configured,
            effective=effective.effective,
            current=current,
            scope=effective.scope.value,
            source=effective.source.value,
            enforced_by=enforced_by,
            message=message or f"Stopped by {constraint_id}",
            task_id=context.task_id if context else None,
            agent_id=context.agent_id if context else None,
        )
        self.record_limit_event(event)
        return event.to_public()

    # ── public aggregates ───────────────────────────────────────────────────

    def definitions(self, *, category: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        items = self.registry.public_definitions()
        if category:
            items = [i for i in items if i["category"] == category]
        if q:
            needle = q.lower()
            items = [
                i
                for i in items
                if needle in i["id"].lower()
                or needle in i["label"].lower()
                or needle in i["description"].lower()
                or needle in i["storage_key"].lower()
            ]
        return items

    def effective_map(self, context: ResolveContext | None = None) -> dict[str, Any]:
        context = context or ResolveContext()
        result = {}
        for definition in self.registry.all():
            result[definition.id] = self.resolve(definition.id, context).to_public()
        return result

    def history(self, *, key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            if key:
                rows = db.execute(
                    "SELECT key, old_value, new_value, scope, scope_id, actor, timestamp "
                    "FROM setting_history WHERE key = ? ORDER BY id DESC LIMIT ?",
                    (key, max(1, int(limit))),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT key, old_value, new_value, scope, scope_id, actor, timestamp "
                    "FROM setting_history ORDER BY id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        return [
            {
                "key": row["key"],
                "old_value": redact_history_value(
                    row["key"],
                    json.loads(row["old_value"]) if row["old_value"] is not None else None,
                ),
                "new_value": redact_history_value(
                    row["key"],
                    json.loads(row["new_value"]) if row["new_value"] is not None else None,
                ),
                "scope": row["scope"],
                "scope_id": row["scope_id"],
                "actor": row["actor"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def dashboard(self, context: ResolveContext | None = None) -> dict[str, Any]:
        context = context or ResolveContext()
        return {
            "config_schema_version": self.schema_version(),
            "cache_version": self.cache_version,
            "categories": self.registry.categories(),
            "definition_count": len(self.registry.all()),
            "presets": list_presets(),
            "immutable_constraints": public_immutable(),
            "capabilities": self.capabilities.public(),
            "values": self.global_values(),
            "recent_limit_events": self.recent_limit_events(20),
            "recent_events": control_events.recent(20),
        }

    def shared_budget_config(self) -> dict[str, Any]:
        """Build shared budget pool configuration from resolved settings."""
        ctx = ResolveContext()
        per_task = self.get("agents.execution.max_model_calls_per_task", ctx)
        multiplier = self.get("runtime.shared_budget.model_calls_multiplier", ctx) or 20
        shared_model = self.get("runtime.shared_budget.max_model_calls", ctx)
        if shared_model is None and per_task is not None:
            shared_model = int(per_task) * int(multiplier)
        return {
            "max_active_tasks": self.get("runtime.shared_budget.max_active_tasks", ctx),
            "max_model_calls": shared_model,
            "max_tool_calls": self.get("runtime.shared_budget.max_tool_calls", ctx),
            "max_specialist_steps": self.get("runtime.shared_budget.max_specialist_steps", ctx),
            "max_plugin_processes": self.get("plugins.max_plugin_processes", ctx),
            "max_subtasks": self.get("runtime.shared_budget.max_subtasks", ctx),
            "max_runtime_seconds": self.get("runtime.shared_budget.max_runtime_seconds", ctx),
        }

    def profile_config_overlay(self, profile_name: str) -> dict[str, Any]:
        """Resolve reasoning profile knobs from settings (defaults match PROFILE_CONFIGS)."""
        prefix = f"reasoning.profiles.{profile_name}."
        keys = [
            "retrieval_limit",
            "max_tool_rounds",
            "max_replans",
            "max_model_calls",
            "context_chars",
            "min_max_tokens",
            "verify",
            "require_plan",
            "allow_specialists",
        ]
        out: dict[str, Any] = {}
        for key in keys:
            out[key] = self.get(f"{prefix}{key}")
        return out


# Process-local singleton set by main.py during startup.
_control_service: ControlService | None = None
_control_lock = threading.Lock()


def get_control_service() -> ControlService:
    if _control_service is None:
        raise RuntimeError("ControlService is not initialized")
    return _control_service


def init_control_service(database: Any, platform_db: Any | None = None) -> ControlService:
    global _control_service
    with _control_lock:
        _control_service = ControlService(database, platform_db)
        return _control_service


def resolve_setting(setting_id: str, context: ResolveContext | None = None, default: Any = None) -> Any:
    """Convenience for runtime call sites."""
    try:
        return get_control_service().get(setting_id, context, default=default)
    except RuntimeError:
        return default
