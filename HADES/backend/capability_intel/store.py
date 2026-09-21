"""SQLite persistence for canonical capabilities, metrics, missions and messages."""

from __future__ import annotations

import json
from typing import Any

from platform_db import utc_now

from .contracts import CanonicalCapability
from .taxonomy import CONTRACT_VERSION


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS capability_records (
    canonical_id TEXT PRIMARY KEY,
    plugin_id TEXT,
    kind TEXT NOT NULL,
    provider_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    contract_version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_records_plugin ON capability_records(plugin_id, kind);
CREATE INDEX IF NOT EXISTS idx_capability_records_kind ON capability_records(kind, provider_id);

CREATE TABLE IF NOT EXISTS capability_metrics (
    key TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    execution_successes INTEGER NOT NULL DEFAULT 0,
    verified_successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    timeouts INTEGER NOT NULL DEFAULT 0,
    latency_ms_sum INTEGER NOT NULL DEFAULT 0,
    model_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached_tokens INTEGER,
    last_failure TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_missions (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_messages (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_messages_mission ON capability_messages(mission_id, created_at);

CREATE TABLE IF NOT EXISTS capability_routing_cache (
    cache_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_capability_schema(db: Any) -> None:
    with db.connection() as conn:
        conn.executescript(SCHEMA_SQL)


def replace_plugin_capabilities(db: Any, plugin_id: str, records: list[CanonicalCapability]) -> int:
    ensure_capability_schema(db)
    now = utc_now()
    with db.connection() as conn:
        conn.execute("DELETE FROM capability_records WHERE plugin_id = ?", (plugin_id,))
        for record in records:
            conn.execute(
                """
                INSERT INTO capability_records
                (canonical_id, plugin_id, kind, provider_id, name, contract_version, content_hash, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.canonical_id,
                    plugin_id,
                    record.kind,
                    record.provider_id,
                    record.name,
                    int(record.contract_version or CONTRACT_VERSION),
                    record.content_hash,
                    json.dumps(record.to_dict(), ensure_ascii=False),
                    now,
                ),
            )
    return len(records)


def replace_native_capabilities(db: Any, records: list[CanonicalCapability]) -> int:
    ensure_capability_schema(db)
    now = utc_now()
    with db.connection() as conn:
        conn.execute("DELETE FROM capability_records WHERE plugin_id IS NULL OR plugin_id = ''")
        for record in records:
            conn.execute(
                """
                INSERT INTO capability_records
                (canonical_id, plugin_id, kind, provider_id, name, contract_version, content_hash, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.canonical_id,
                    None,
                    record.kind,
                    record.provider_id,
                    record.name,
                    int(record.contract_version or CONTRACT_VERSION),
                    record.content_hash,
                    json.dumps(record.to_dict(), ensure_ascii=False),
                    now,
                ),
            )
    return len(records)


def load_capabilities(db: Any, *, plugin_id: str | None = None) -> list[CanonicalCapability]:
    ensure_capability_schema(db)
    sql = "SELECT payload_json FROM capability_records"
    args: tuple[Any, ...] = ()
    if plugin_id is not None:
        sql += " WHERE plugin_id = ?"
        args = (plugin_id,)
    rows: list[CanonicalCapability] = []
    with db.connection() as conn:
        for (payload,) in conn.execute(sql, args).fetchall():
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if isinstance(data, dict):
                rows.append(CanonicalCapability.from_mapping(data))
    return rows


def remove_plugin_capabilities(db: Any, plugin_id: str) -> None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        conn.execute("DELETE FROM capability_records WHERE plugin_id = ?", (plugin_id,))


def upsert_metric(db: Any, key: str, fields: dict[str, Any]) -> None:
    ensure_capability_schema(db)
    now = utc_now()
    with db.connection() as conn:
        existing = conn.execute("SELECT * FROM capability_metrics WHERE key = ?", (key,)).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO capability_metrics
                (key, provider_id, capability_id, version, domain, attempts, execution_successes,
                 verified_successes, failures, timeouts, latency_ms_sum, model_calls,
                 input_tokens, output_tokens, cached_tokens, last_failure, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    fields.get("provider_id") or "",
                    fields.get("capability_id") or "",
                    fields.get("version") or "",
                    fields.get("domain") or "",
                    int(fields.get("attempts") or 0),
                    int(fields.get("execution_successes") or 0),
                    int(fields.get("verified_successes") or 0),
                    int(fields.get("failures") or 0),
                    int(fields.get("timeouts") or 0),
                    int(fields.get("latency_ms_sum") or 0),
                    int(fields.get("model_calls") or 0),
                    fields.get("input_tokens"),
                    fields.get("output_tokens"),
                    fields.get("cached_tokens"),
                    fields.get("last_failure"),
                    now,
                ),
            )
            return
        # Agents may not rewrite weights; only the runtime increments counters.
        conn.execute(
            """
            UPDATE capability_metrics SET
                attempts = attempts + ?,
                execution_successes = execution_successes + ?,
                verified_successes = verified_successes + ?,
                failures = failures + ?,
                timeouts = timeouts + ?,
                latency_ms_sum = latency_ms_sum + ?,
                model_calls = model_calls + ?,
                last_failure = COALESCE(?, last_failure),
                updated_at = ?
            WHERE key = ?
            """,
            (
                int(fields.get("attempts") or 0),
                int(fields.get("execution_successes") or 0),
                int(fields.get("verified_successes") or 0),
                int(fields.get("failures") or 0),
                int(fields.get("timeouts") or 0),
                int(fields.get("latency_ms_sum") or 0),
                int(fields.get("model_calls") or 0),
                fields.get("last_failure"),
                now,
                key,
            ),
        )


def load_metrics(db: Any) -> list[dict[str, Any]]:
    ensure_capability_schema(db)
    with db.connection() as conn:
        cols = [item[1] for item in conn.execute("PRAGMA table_info(capability_metrics)").fetchall()]
        rows = conn.execute("SELECT * FROM capability_metrics").fetchall()
    return [dict(zip(cols, row)) for row in rows]


def save_mission(db: Any, mission_id: str, payload: dict[str, Any], status: str) -> None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO capability_missions (id, payload_json, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET payload_json = excluded.payload_json, status = excluded.status, updated_at = excluded.updated_at
            """,
            (mission_id, json.dumps(payload, ensure_ascii=False), status, utc_now()),
        )


def load_mission(db: Any, mission_id: str) -> dict[str, Any] | None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM capability_missions WHERE id = ?", (mission_id,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row[0])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def append_message(db: Any, mission_id: str, message_id: str, payload: dict[str, Any]) -> None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO capability_messages (id, mission_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (message_id, mission_id, json.dumps(payload, ensure_ascii=False), utc_now()),
        )


def load_messages(db: Any, mission_id: str) -> list[dict[str, Any]]:
    ensure_capability_schema(db)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM capability_messages WHERE mission_id = ? ORDER BY created_at ASC",
            (mission_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for (payload,) in rows:
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def cache_get(db: Any, cache_key: str, state_hash: str) -> dict[str, Any] | None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT payload_json, state_hash FROM capability_routing_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if not row:
        return None
    if row[1] != state_hash:
        return None
    try:
        data = json.loads(row[0])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def cache_put(db: Any, cache_key: str, state_hash: str, payload: dict[str, Any]) -> None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO capability_routing_cache (cache_key, payload_json, state_hash, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET payload_json = excluded.payload_json, state_hash = excluded.state_hash, created_at = excluded.created_at
            """,
            (cache_key, json.dumps(payload, ensure_ascii=False), state_hash, utc_now()),
        )


def cache_invalidate(db: Any, prefix: str | None = None) -> int:
    ensure_capability_schema(db)
    with db.connection() as conn:
        if prefix:
            cur = conn.execute("DELETE FROM capability_routing_cache WHERE cache_key LIKE ?", (f"{prefix}%",))
        else:
            cur = conn.execute("DELETE FROM capability_routing_cache")
        return int(cur.rowcount or 0)


def record_failure(db: Any, *, mission_id: str, provider_id: str, capability_id: str, kind: str, detail: str = "") -> None:
    ensure_capability_schema(db)
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO capability_failures (mission_id, provider_id, capability_id, kind, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mission_id, provider_id, capability_id, kind, detail, utc_now()),
        )


def mission_failures(db: Any, mission_id: str) -> list[dict[str, Any]]:
    ensure_capability_schema(db)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT provider_id, capability_id, kind, detail FROM capability_failures WHERE mission_id = ?",
            (mission_id,),
        ).fetchall()
    return [
        {"provider_id": provider_id, "capability_id": capability_id, "kind": kind, "detail": detail}
        for provider_id, capability_id, kind, detail in rows
    ]
