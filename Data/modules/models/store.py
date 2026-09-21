"""Central SQLite persistence for the Model Control Plane."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ModelStore:
    """Owns model registry / provider / profile / router / download rows.

    Uses the central LEVIATHAN database path — no parallel DB.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Providers ---

    def list_providers(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_providers ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_providers WHERE provider_id = ?",
                (provider_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_provider(self, record: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_providers(
                    provider_id, name, provider_type, endpoint, enabled,
                    api_key_ciphertext, auto_connect, timeout_seconds,
                    refresh_interval_seconds, health, last_successful_at,
                    last_error, last_latency_ms, last_check_at,
                    capabilities_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    name=excluded.name,
                    provider_type=excluded.provider_type,
                    endpoint=excluded.endpoint,
                    enabled=excluded.enabled,
                    api_key_ciphertext=COALESCE(excluded.api_key_ciphertext, model_providers.api_key_ciphertext),
                    auto_connect=excluded.auto_connect,
                    timeout_seconds=excluded.timeout_seconds,
                    refresh_interval_seconds=excluded.refresh_interval_seconds,
                    health=excluded.health,
                    last_successful_at=excluded.last_successful_at,
                    last_error=excluded.last_error,
                    last_latency_ms=excluded.last_latency_ms,
                    last_check_at=excluded.last_check_at,
                    capabilities_json=excluded.capabilities_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record["provider_id"],
                    record["name"],
                    record["provider_type"],
                    record["endpoint"],
                    1 if record.get("enabled", True) else 0,
                    record.get("api_key_ciphertext"),
                    1 if record.get("auto_connect", True) else 0,
                    float(record.get("timeout_seconds", 30.0)),
                    float(record.get("refresh_interval_seconds", 60.0)),
                    record.get("health", "unknown"),
                    record.get("last_successful_at"),
                    record.get("last_error"),
                    record.get("last_latency_ms"),
                    record.get("last_check_at"),
                    json.dumps(record.get("capabilities") or {}),
                    json.dumps(record.get("metadata") or {}),
                    record.get("created_at") or now,
                    now,
                ),
            )

    def update_provider_fields(self, provider_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "name",
            "endpoint",
            "enabled",
            "api_key_ciphertext",
            "auto_connect",
            "timeout_seconds",
            "refresh_interval_seconds",
            "health",
            "last_successful_at",
            "last_error",
            "last_latency_ms",
            "last_check_at",
            "capabilities_json",
            "metadata_json",
        }
        sets: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"enabled", "auto_connect"} and isinstance(value, bool):
                value = 1 if value else 0
            if key in {"capabilities_json", "metadata_json"} and not isinstance(value, str):
                value = json.dumps(value or {})
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return
        sets.append("updated_at = ?")
        values.append(utc_now())
        values.append(provider_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE model_providers SET {', '.join(sets)} WHERE provider_id = ?",
                values,
            )

    def delete_provider(self, provider_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM model_providers WHERE provider_id = ?",
                (provider_id,),
            )
            return cur.rowcount > 0

    # --- Registry ---

    def list_models(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_registry ORDER BY display_name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_registry WHERE model_id = ?",
                (model_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_model(self, record: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_registry(
                    model_id, display_name, provider_id, runtime_id, source,
                    object_type, architecture, family, parameter_count,
                    quantization, format, disk_size_bytes, context_window,
                    max_output_tokens, capabilities_json, lifecycle_state,
                    health, active, loaded, local_path, endpoint,
                    last_discovered_at, last_used_at, tags_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    provider_id=excluded.provider_id,
                    runtime_id=excluded.runtime_id,
                    source=excluded.source,
                    object_type=excluded.object_type,
                    architecture=excluded.architecture,
                    family=excluded.family,
                    parameter_count=excluded.parameter_count,
                    quantization=excluded.quantization,
                    format=excluded.format,
                    disk_size_bytes=excluded.disk_size_bytes,
                    context_window=excluded.context_window,
                    max_output_tokens=excluded.max_output_tokens,
                    capabilities_json=excluded.capabilities_json,
                    lifecycle_state=excluded.lifecycle_state,
                    health=excluded.health,
                    active=excluded.active,
                    loaded=excluded.loaded,
                    local_path=excluded.local_path,
                    endpoint=excluded.endpoint,
                    last_discovered_at=excluded.last_discovered_at,
                    last_used_at=COALESCE(excluded.last_used_at, model_registry.last_used_at),
                    tags_json=excluded.tags_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record["model_id"],
                    record["display_name"],
                    record["provider_id"],
                    record.get("runtime_id"),
                    record.get("source", "remote"),
                    record.get("object_type"),
                    record.get("architecture"),
                    record.get("family"),
                    record.get("parameter_count"),
                    record.get("quantization"),
                    record.get("format"),
                    record.get("disk_size_bytes"),
                    record.get("context_window"),
                    record.get("max_output_tokens"),
                    json.dumps(record.get("capabilities") or {}),
                    record.get("lifecycle_state", "discovered"),
                    record.get("health", "unknown"),
                    1 if record.get("active") else 0,
                    None if record.get("loaded") is None else (1 if record.get("loaded") else 0),
                    record.get("local_path"),
                    record.get("endpoint"),
                    record.get("last_discovered_at") or now,
                    record.get("last_used_at"),
                    json.dumps(list(record.get("tags") or [])),
                    json.dumps(record.get("metadata") or {}),
                    record.get("created_at") or now,
                    now,
                ),
            )

    def set_active_model(self, model_id: str | None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE model_registry SET active = 0")
            if model_id:
                conn.execute(
                    "UPDATE model_registry SET active = 1, lifecycle_state = CASE "
                    "WHEN lifecycle_state IN ('loaded','active') THEN 'active' "
                    "ELSE lifecycle_state END, updated_at = ? WHERE model_id = ?",
                    (utc_now(), model_id),
                )
            conn.execute(
                """
                INSERT INTO model_control_state(key, value_json, updated_at)
                VALUES ('active_model_id', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (json.dumps(model_id), utc_now()),
            )

    def get_active_model_id(self) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM model_control_state WHERE key = 'active_model_id'"
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["value_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, str) and value else None

    def delete_model(self, model_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM model_registry WHERE model_id = ?",
                (model_id,),
            )
            conn.execute("DELETE FROM model_profiles WHERE model_id = ?", (model_id,))
            conn.execute(
                "DELETE FROM model_capability_results WHERE model_id = ?",
                (model_id,),
            )
            return cur.rowcount > 0

    def mark_provider_models_offline(self, provider_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE model_registry
                SET lifecycle_state = 'offline', health = 'offline', loaded = 0, updated_at = ?
                WHERE provider_id = ?
                """,
                (utc_now(), provider_id),
            )

    # --- Profiles ---

    def get_profile(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_profiles WHERE model_id = ?",
                (model_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_profile(self, record: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_profiles(
                    model_id, temperature, top_p, top_k, max_tokens,
                    repeat_penalty, seed, system_prompt, active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    temperature=excluded.temperature,
                    top_p=excluded.top_p,
                    top_k=excluded.top_k,
                    max_tokens=excluded.max_tokens,
                    repeat_penalty=excluded.repeat_penalty,
                    seed=excluded.seed,
                    system_prompt=excluded.system_prompt,
                    active=excluded.active,
                    updated_at=excluded.updated_at
                """,
                (
                    record["model_id"],
                    float(record["temperature"]),
                    float(record["top_p"]),
                    int(record["top_k"]),
                    int(record["max_tokens"]),
                    float(record["repeat_penalty"]),
                    int(record["seed"]),
                    str(record.get("system_prompt") or ""),
                    1 if record.get("active") else 0,
                    now,
                ),
            )

    def clear_active_profiles(self) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE model_profiles SET active = 0")

    # --- Router / streaming preferences ---

    def get_router_config(self) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM model_control_state WHERE key = 'router_config'"
            ).fetchone()
        if not row:
            return {
                "fallback_order": [],
                "role_overrides": {},
                "cloud_fallback_allowed": False,
                "streaming": True,
                "stream_provisional_text": True,
                "progress_events_enabled": True,
            }
        try:
            data = json.loads(row["value_json"])
        except (TypeError, json.JSONDecodeError):
            data = {}
        return {
            "fallback_order": list(data.get("fallback_order") or []),
            "role_overrides": dict(data.get("role_overrides") or {}),
            "cloud_fallback_allowed": bool(data.get("cloud_fallback_allowed", False)),
            "streaming": bool(data.get("streaming", True)),
            "stream_provisional_text": bool(data.get("stream_provisional_text", True)),
            "progress_events_enabled": bool(data.get("progress_events_enabled", True)),
        }

    def save_router_config(self, config: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_control_state(key, value_json, updated_at)
                VALUES ('router_config', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (json.dumps(config), utc_now()),
            )

    # --- Capability results ---

    def list_capability_results(self, model_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_capability_results WHERE model_id = ?",
                (model_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_capability_result(self, record: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_capability_results(
                    model_id, capability, declared, verified, last_tested_at, detail
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id, capability) DO UPDATE SET
                    declared=excluded.declared,
                    verified=excluded.verified,
                    last_tested_at=excluded.last_tested_at,
                    detail=excluded.detail
                """,
                (
                    record["model_id"],
                    record["capability"],
                    record["declared"],
                    record["verified"],
                    record.get("last_tested_at"),
                    record.get("detail"),
                ),
            )

    # --- Downloads ---

    def list_downloads(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_downloads ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_download(self, download_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_downloads WHERE download_id = ?",
                (download_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_download(self, record: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_downloads(
                    download_id, state, source, repository_id, revision,
                    destination, bytes_downloaded, total_bytes, speed_bps,
                    eta_seconds, error, model_id, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(download_id) DO UPDATE SET
                    state=excluded.state,
                    source=excluded.source,
                    repository_id=excluded.repository_id,
                    revision=excluded.revision,
                    destination=excluded.destination,
                    bytes_downloaded=excluded.bytes_downloaded,
                    total_bytes=excluded.total_bytes,
                    speed_bps=excluded.speed_bps,
                    eta_seconds=excluded.eta_seconds,
                    error=excluded.error,
                    model_id=excluded.model_id,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record["download_id"],
                    record["state"],
                    record["source"],
                    record.get("repository_id"),
                    record.get("revision"),
                    record.get("destination"),
                    record.get("bytes_downloaded"),
                    record.get("total_bytes"),
                    record.get("speed_bps"),
                    record.get("eta_seconds"),
                    record.get("error"),
                    record.get("model_id"),
                    record.get("created_at") or now,
                    now,
                    json.dumps(record.get("metadata") or {}),
                ),
            )

    # --- Audit ---

    def append_audit(self, action: str, *, actor: str = "system", detail: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_audit_log(created_at, actor, action, detail_json)
                VALUES (?, ?, ?, ?)
                """,
                (utc_now(), actor, action, json.dumps(detail or {})),
            )

    def recent_audit(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_audit_log ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]
