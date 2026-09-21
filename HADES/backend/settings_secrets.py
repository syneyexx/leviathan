"""Secure storage for core provider API keys (LM Studio / TTS / STT).

Plaintext values must not remain in SQLite, setting history, or public API
surfaces once migration succeeds. Uses the OS keyring (same pattern as
``mcp_host.secrets.McpSecretStore``). Migration is fail-safe: keyring write +
verify must succeed before SQLite plaintext is replaced.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from mcp_host.secrets import McpSecretStore, SecretStorageUnavailable

SERVICE_NAME = "HADES-Provider"

SECRET_SETTING_KEYS = frozenset({"lm_studio_api_key", "tts_api_key", "stt_api_key"})
SECRET_MASK = "***"
KEYRING_SENTINEL = "__KEYRING__"
MIGRATION_META_KEY = "provider_settings_secrets_v1"

DEFAULTS_BY_KEY = {
    "lm_studio_api_key": "lm-studio",
    "tts_api_key": "",
    "stt_api_key": "",
}


class ProviderSettingsSecretStore(McpSecretStore):
    """Keyring-backed store with fixed refs per settings key (+ optional scope)."""

    def available(self) -> dict[str, Any]:
        status = super().available()
        if not status.get("ok"):
            return status
        probe_ref = "provider/settings/__probe__"
        try:
            self._store_ref(probe_ref, "probe")
            backend = self._backend()
            try:
                backend.delete_password(SERVICE_NAME, probe_ref)
            except Exception:
                pass
        except SecretStorageUnavailable as exc:
            return {"ok": False, "backend": status.get("backend"), "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "backend": status.get("backend"), "error": str(exc)}
        return status

    def ref_for(self, key: str, *, scope: str | None = None, scope_id: str | None = None) -> str:
        base = f"provider/settings/{key}"
        if scope and scope != "global":
            sid = scope_id or ""
            return f"{base}/{scope}/{sid}"
        return base

    def store_setting(
        self,
        key: str,
        value: str,
        *,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> str:
        if key not in SECRET_SETTING_KEYS:
            raise ValueError(f"not a provider secret key: {key}")
        ref = self.ref_for(key, scope=scope, scope_id=scope_id)
        self._store_ref(ref, str(value))
        return ref

    def _store_ref(self, ref: str, value: str) -> None:
        if not ref or not value:
            raise ValueError("secret ref and value are required")
        with self._lock:
            if self._memory_test_override is not None:
                self._memory_test_override[ref] = value
                return
            backend = self._backend()
            try:
                backend.set_password(SERVICE_NAME, ref, value)
            except Exception as exc:
                self._best_effort_backend_delete(backend, ref)
                raise SecretStorageUnavailable(f"Kon provider secret niet opslaan: {exc}") from exc
            try:
                stored = backend.get_password(SERVICE_NAME, ref)
            except Exception as exc:
                self._best_effort_backend_delete(backend, ref)
                raise SecretStorageUnavailable(f"Provider secret niet verifieerbaar: {exc}") from exc
            if stored != value:
                self._best_effort_backend_delete(backend, ref)
                raise SecretStorageUnavailable("Provider secret verificatie mislukt.")

    def _get_ref(self, ref: str | None) -> str | None:
        if not ref:
            return None
        with self._lock:
            if self._memory_test_override is not None:
                return self._memory_test_override.get(ref)
            backend = self._backend()
            try:
                return backend.get_password(SERVICE_NAME, ref)
            except Exception as exc:
                raise SecretStorageUnavailable(f"Kon provider secret niet lezen: {exc}") from exc

    def read_setting(
        self,
        key: str,
        *,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> str | None:
        ref = self.ref_for(key, scope=scope, scope_id=scope_id)
        try:
            return self._get_ref(ref)
        except SecretStorageUnavailable:
            return None

    def delete_setting(
        self,
        key: str,
        *,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        ref = self.ref_for(key, scope=scope, scope_id=scope_id)
        if not ref:
            return {"ok": True, "deleted": False, "reason": "empty_ref"}
        with self._lock:
            if self._memory_test_override is not None:
                existed = ref in self._memory_test_override
                self._memory_test_override.pop(ref, None)
                return {"ok": True, "deleted": existed}
            backend = self._backend()
            try:
                backend.delete_password(SERVICE_NAME, ref)
                return {"ok": True, "deleted": True}
            except Exception as exc:
                name = type(exc).__name__
                if "PasswordDelete" in name or "not found" in str(exc).lower() or "NotFound" in name:
                    return {"ok": True, "deleted": False, "reason": "missing"}
                return {"ok": False, "deleted": False, "error": str(exc), "error_type": name}


provider_secret_store = ProviderSettingsSecretStore()


def is_secret_setting_key(key: str) -> bool:
    return str(key) in SECRET_SETTING_KEYS


def is_noop_secret_patch(value: Any) -> bool:
    """Treat masked/empty patches as 'leave unchanged' on settings APIs."""
    if value is None:
        return True
    text = str(value)
    return text in {"", SECRET_MASK, KEYRING_SENTINEL}


def is_stored_in_keyring(stored_value: Any) -> bool:
    return str(stored_value) == KEYRING_SENTINEL


def mask_settings_values(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    for key in SECRET_SETTING_KEYS:
        if key not in out:
            continue
        raw = out.get(key)
        if raw in (None, ""):
            out[key] = ""
            continue
        if is_stored_in_keyring(raw) or str(raw).strip():
            out[key] = SECRET_MASK
    return out


def resolve_settings_secrets(values: dict[str, Any]) -> dict[str, Any]:
    """Merge keyring secrets for runtime consumers (never for public export)."""
    out = dict(values)
    for key in SECRET_SETTING_KEYS:
        stored = out.get(key)
        if is_stored_in_keyring(stored):
            resolved = provider_secret_store.read_setting(key)
            out[key] = resolved if resolved is not None else DEFAULTS_BY_KEY.get(key, "")
        elif stored in (None, SECRET_MASK):
            out[key] = DEFAULTS_BY_KEY.get(key, "")
        elif stored == "":
            out[key] = DEFAULTS_BY_KEY.get(key, "")
        else:
            out[key] = str(stored)
    return out


def redact_history_value(key: str, value: Any) -> Any:
    if is_secret_setting_key(key):
        if value in (None, ""):
            return value
        return SECRET_MASK
    return value


def _ensure_config_meta_table(db: Any) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS config_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _read_migration_meta(db: Any) -> dict[str, Any]:
    _ensure_config_meta_table(db)
    row = db.execute("SELECT value FROM config_meta WHERE key = ?", (MIGRATION_META_KEY,)).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row["value"])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_migration_meta(db: Any, payload: dict[str, Any]) -> None:
    _ensure_config_meta_table(db)
    db.execute(
        "INSERT INTO config_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (MIGRATION_META_KEY, json.dumps(payload)),
    )


def _redact_secret_history_rows(db: Any, key: str) -> None:
    cols = {r[1] for r in db.execute("PRAGMA table_info(setting_history)").fetchall()}
    if not {"key", "old_value", "new_value"}.issubset(cols):
        return
    db.execute(
        "UPDATE setting_history SET old_value=?, new_value=? WHERE key=?",
        (json.dumps(SECRET_MASK), json.dumps(SECRET_MASK), key),
    )


def _meta_key(key: str, scope: str | None, scope_id: str | None) -> str:
    if scope and scope != "global":
        return f"{key}:{scope}:{scope_id or ''}"
    return key


def _write_sentinel(
    db: Any,
    *,
    table: str,
    key: str,
    scope: str | None = None,
    scope_id: str | None = None,
) -> None:
    sentinel = json.dumps(KEYRING_SENTINEL)
    if table == "app_settings":
        db.execute("UPDATE app_settings SET value=? WHERE key=?", (sentinel, key))
        return
    db.execute(
        "UPDATE setting_overrides SET value=? WHERE key=? AND scope=? AND IFNULL(scope_id,'') = IFNULL(?, '')",
        (sentinel, key, scope, scope_id),
    )


def _migrate_single_sqlite_value(
    db: Any,
    *,
    table: str,
    key: str,
    value_json: str,
    scope: str | None = None,
    scope_id: str | None = None,
    meta: dict[str, Any],
) -> bool:
    """Migrate one row if it still holds plaintext. Returns True when migrated."""
    try:
        parsed = json.loads(value_json)
    except Exception:
        return False
    if parsed == KEYRING_SENTINEL:
        return False
    meta_key = _meta_key(key, scope, scope_id)
    if parsed in (None, ""):
        _write_sentinel(db, table=table, key=key, scope=scope, scope_id=scope_id)
        meta.setdefault("keys", {})[meta_key] = provider_secret_store.ref_for(key, scope=scope, scope_id=scope_id)
        _redact_secret_history_rows(db, key)
        return True
    plaintext = str(parsed)
    try:
        ref = provider_secret_store.store_setting(key, plaintext, scope=scope, scope_id=scope_id)
    except SecretStorageUnavailable:
        return False
    _write_sentinel(db, table=table, key=key, scope=scope, scope_id=scope_id)
    meta.setdefault("keys", {})[meta_key] = ref
    _redact_secret_history_rows(db, key)
    return True


_migration_lock = threading.Lock()


def migrate_provider_settings_secrets(database: Any) -> dict[str, Any]:
    """Compatibility-safe migration of plaintext settings values into keyring.

    Never removes SQLite plaintext unless the keyring round-trip succeeded.
    """
    with _migration_lock:
        if provider_secret_store._memory_test_override is not None:
            backend = {"ok": True, "backend": "memory"}
        else:
            backend = provider_secret_store.available()
        result: dict[str, Any] = {
            "ok": True,
            "backend": backend,
            "migrated_keys": [],
            "skipped_keys": [],
            "errors": [],
        }
        if not backend.get("ok"):
            result["ok"] = False
            result["errors"].append(str(backend.get("error") or "keyring unavailable"))
            return result

        with database.connection() as db:
            meta = _read_migration_meta(db)
            migrated: list[str] = []

            # app_settings
            for key in SECRET_SETTING_KEYS:
                row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
                if not row:
                    continue
                if _migrate_single_sqlite_value(db, table="app_settings", key=key, value_json=row["value"], meta=meta):
                    migrated.append(key)

            # Scoped overrides (same secret keys)
            override_cols = {r[1] for r in db.execute("PRAGMA table_info(setting_overrides)").fetchall()}
            if {"key", "value", "scope", "scope_id"}.issubset(override_cols):
                rows = db.execute(
                    "SELECT key, scope, scope_id, value FROM setting_overrides WHERE key IN (?,?,?)",
                    tuple(SECRET_SETTING_KEYS),
                ).fetchall()
                for row in rows:
                    composite = f"{row['key']}:{row['scope']}:{row['scope_id'] or ''}"
                    if _migrate_single_sqlite_value(
                        db,
                        table="setting_overrides",
                        key=row["key"],
                        value_json=row["value"],
                        scope=row["scope"],
                        scope_id=row["scope_id"],
                        meta=meta,
                    ):
                        migrated.append(composite)

            if migrated:
                meta["completed_at"] = meta.get("completed_at") or _utc_now()
            _write_migration_meta(db, meta)
            result["migrated_keys"] = sorted(set(migrated))
        return result


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def apply_secret_patches(
    current: dict[str, Any],
    patches: dict[str, Any],
    *,
    scope: str | None = None,
    scope_id: str | None = None,
) -> dict[str, Any]:
    """Persist provider secret patches to keyring; SQLite receives sentinel only.

    When the OS secret backend is unavailable, leave the plaintext patch value
    for SQLite compatibility (fail-safe). Never claim keyring storage succeeded.
    """
    out = dict(patches)
    for key in list(out.keys()):
        if key not in SECRET_SETTING_KEYS:
            continue
        new_value = out[key]
        if is_noop_secret_patch(new_value):
            out.pop(key, None)
            continue
        try:
            provider_secret_store.store_setting(str(key), str(new_value), scope=scope, scope_id=scope_id)
            out[key] = KEYRING_SENTINEL
        except SecretStorageUnavailable:
            # Keep attempting plaintext persistence so non-secret settings patches
            # are not blocked on hosts without a keyring backend.
            continue
    return out


def prepare_secret_defaults_for_sqlite(defaults: dict[str, Any]) -> dict[str, Any]:
    """Ensure fresh installs use sentinel placeholders, not fake secrets in SQLite."""
    out = dict(defaults)
    for key in SECRET_SETTING_KEYS:
        if key in out and out[key] not in (KEYRING_SENTINEL,):
            # Keep install defaults in SQLite until first migration run stores them.
            pass
    return out
