"""Central SQLite persistence for MCP servers, tools, and call history."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    McpCallStatus,
    McpIsolationKind,
    McpServerConfig,
    McpServerRuntime,
    McpServerState,
    McpSourceKind,
    McpToolAvailability,
    McpToolCallRecord,
    McpToolRecord,
    McpTransportKind,
    McpTrust,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class McpStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mcp_servers (
                server_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_key TEXT NOT NULL,
                owner_module_id TEXT,
                transport TEXT NOT NULL,
                command TEXT,
                args_json TEXT NOT NULL DEFAULT '[]',
                url TEXT,
                cwd TEXT,
                env_public_json TEXT NOT NULL DEFAULT '{}',
                secret_refs_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 0,
                trust TEXT NOT NULL DEFAULT 'untrusted',
                requested_isolation TEXT NOT NULL DEFAULT 'subprocess',
                effective_isolation TEXT NOT NULL DEFAULT 'subprocess',
                timeout_seconds REAL NOT NULL DEFAULT 30,
                max_concurrent_calls INTEGER NOT NULL DEFAULT 4,
                eager_connect INTEGER NOT NULL DEFAULT 0,
                expand_tools INTEGER NOT NULL DEFAULT 1,
                semantic_effects_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                current_state TEXT NOT NULL DEFAULT 'DISCONNECTED',
                last_connected_at TEXT,
                last_seen_at TEXT,
                last_error_code TEXT,
                last_error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_kind, source_key)
            );

            CREATE TABLE IF NOT EXISTS mcp_tools (
                capability_id TEXT PRIMARY KEY,
                server_id TEXT NOT NULL,
                external_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                input_schema_json TEXT NOT NULL DEFAULT '{}',
                schema_hash TEXT NOT NULL,
                semantic_effects_json TEXT NOT NULL DEFAULT '[]',
                availability TEXT NOT NULL DEFAULT 'unavailable',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                server_version TEXT,
                protocol_version TEXT,
                UNIQUE(server_id, external_name),
                FOREIGN KEY(server_id) REFERENCES mcp_servers(server_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_mcp_tools_server
                ON mcp_tools(server_id, external_name);

            CREATE TABLE IF NOT EXISTS mcp_tool_calls (
                call_id TEXT PRIMARY KEY,
                trace_id TEXT,
                server_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                external_tool_name TEXT NOT NULL,
                requester TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL,
                approval_id TEXT,
                arguments_summary TEXT,
                result_summary TEXT,
                error_code TEXT,
                error_message TEXT,
                schema_hash TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_started
                ON mcp_tool_calls(started_at DESC);
            """
        )

    # --- servers ---

    def upsert_server(self, config: McpServerConfig) -> McpServerConfig:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT created_at FROM mcp_servers WHERE server_id = ?",
                (config.server_id,),
            ).fetchone()
            created = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO mcp_servers(
                    server_id, display_name, source_kind, source_key, owner_module_id,
                    transport, command, args_json, url, cwd, env_public_json, secret_refs_json,
                    enabled, trust, requested_isolation, effective_isolation, timeout_seconds,
                    max_concurrent_calls, eager_connect, expand_tools, semantic_effects_json,
                    metadata_json, current_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    owner_module_id=excluded.owner_module_id,
                    transport=excluded.transport,
                    command=excluded.command,
                    args_json=excluded.args_json,
                    url=excluded.url,
                    cwd=excluded.cwd,
                    env_public_json=excluded.env_public_json,
                    secret_refs_json=excluded.secret_refs_json,
                    enabled=excluded.enabled,
                    trust=excluded.trust,
                    requested_isolation=excluded.requested_isolation,
                    timeout_seconds=excluded.timeout_seconds,
                    max_concurrent_calls=excluded.max_concurrent_calls,
                    eager_connect=excluded.eager_connect,
                    expand_tools=excluded.expand_tools,
                    semantic_effects_json=excluded.semantic_effects_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    config.server_id,
                    config.display_name,
                    config.source_kind.value,
                    config.source_key,
                    config.owner_module_id,
                    config.transport.value,
                    config.command,
                    json.dumps(list(config.args)),
                    config.url,
                    config.cwd,
                    json.dumps(config.env_public),
                    json.dumps(config.secret_refs),
                    1 if config.enabled else 0,
                    config.trust.value,
                    config.requested_isolation.value,
                    McpIsolationKind.SUBPROCESS.value,
                    config.timeout_seconds,
                    config.max_concurrent_calls,
                    1 if config.eager_connect else 0,
                    1 if config.expand_tools else 0,
                    json.dumps({k: list(v) for k, v in config.semantic_effects.items()}),
                    json.dumps(config.metadata),
                    McpServerState.DISCONNECTED.value,
                    created,
                    now,
                ),
            )
        return config

    def get_server(self, server_id: str) -> McpServerConfig | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE server_id = ?", (server_id,)
            ).fetchone()
            return self._row_to_config(row) if row else None

    def list_servers(self) -> list[McpServerConfig]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM mcp_servers ORDER BY display_name COLLATE NOCASE"
            ).fetchall()
            return [self._row_to_config(row) for row in rows]

    def delete_server(self, server_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute("DELETE FROM mcp_servers WHERE server_id = ?", (server_id,))
            return cur.rowcount > 0

    def set_enabled(self, server_id: str, enabled: bool) -> McpServerConfig | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE mcp_servers SET enabled = ?, updated_at = ? WHERE server_id = ?",
                (1 if enabled else 0, utc_now(), server_id),
            )
        return self.get_server(server_id)

    def update_runtime_state(
        self,
        server_id: str,
        *,
        state: McpServerState,
        effective_isolation: McpIsolationKind | None = None,
        last_error_code: str | None = None,
        last_error_message: str | None = None,
        connected: bool = False,
        seen: bool = False,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            fields = ["current_state = ?", "updated_at = ?", "last_error_code = ?", "last_error_message = ?"]
            values: list[Any] = [state.value, now, last_error_code, last_error_message]
            if effective_isolation is not None:
                fields.append("effective_isolation = ?")
                values.append(effective_isolation.value)
            if connected:
                fields.append("last_connected_at = ?")
                values.append(now)
            if seen:
                fields.append("last_seen_at = ?")
                values.append(now)
            values.append(server_id)
            conn.execute(
                f"UPDATE mcp_servers SET {', '.join(fields)} WHERE server_id = ?",
                values,
            )

    def load_runtime_snapshot(self, server_id: str) -> McpServerRuntime | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE server_id = ?", (server_id,)
            ).fetchone()
            if not row:
                return None
            tool_count = conn.execute(
                "SELECT COUNT(*) AS c FROM mcp_tools WHERE server_id = ?", (server_id,)
            ).fetchone()["c"]
            return McpServerRuntime(
                server_id=server_id,
                state=McpServerState(row["current_state"]),
                effective_isolation=McpIsolationKind(row["effective_isolation"]),
                last_connected_at=row["last_connected_at"],
                last_seen_at=row["last_seen_at"],
                last_error_code=row["last_error_code"],
                last_error_message=row["last_error_message"],
                tool_count=int(tool_count),
            )

    # --- tools ---

    def upsert_tool(self, record: McpToolRecord) -> McpToolRecord:
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT first_seen_at FROM mcp_tools WHERE capability_id = ?",
                (record.capability_id,),
            ).fetchone()
            first = existing["first_seen_at"] if existing else record.first_seen_at
            conn.execute(
                """
                INSERT INTO mcp_tools(
                    capability_id, server_id, external_name, description, input_schema_json,
                    schema_hash, semantic_effects_json, availability, first_seen_at, last_seen_at,
                    server_version, protocol_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    description=excluded.description,
                    input_schema_json=excluded.input_schema_json,
                    schema_hash=excluded.schema_hash,
                    semantic_effects_json=excluded.semantic_effects_json,
                    availability=excluded.availability,
                    last_seen_at=excluded.last_seen_at,
                    server_version=excluded.server_version,
                    protocol_version=excluded.protocol_version
                """,
                (
                    record.capability_id,
                    record.server_id,
                    record.external_name,
                    record.description,
                    json.dumps(record.input_schema),
                    record.schema_hash,
                    json.dumps(list(record.semantic_effects)),
                    record.availability.value,
                    first,
                    record.last_seen_at,
                    record.server_version,
                    record.protocol_version,
                ),
            )
        return record

    def list_tools(self, *, server_id: str | None = None) -> list[McpToolRecord]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if server_id:
                rows = conn.execute(
                    "SELECT * FROM mcp_tools WHERE server_id = ? ORDER BY external_name",
                    (server_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mcp_tools ORDER BY server_id, external_name"
                ).fetchall()
            return [self._row_to_tool(row) for row in rows]

    def get_tool(self, capability_id: str) -> McpToolRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM mcp_tools WHERE capability_id = ?", (capability_id,)
            ).fetchone()
            return self._row_to_tool(row) if row else None

    def mark_server_tools_unavailable(self, server_id: str, *, reason: str = "server_offline") -> None:
        _ = reason
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE mcp_tools SET availability = ? WHERE server_id = ?",
                (McpToolAvailability.UNAVAILABLE.value, server_id),
            )

    def delete_tools_for_server(self, server_id: str) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))

    # --- calls ---

    def record_call(self, record: McpToolCallRecord) -> McpToolCallRecord:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO mcp_tool_calls(
                    call_id, trace_id, server_id, capability_id, external_tool_name, requester,
                    status, duration_ms, approval_id, arguments_summary, result_summary,
                    error_code, error_message, schema_hash, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.call_id,
                    record.trace_id,
                    record.server_id,
                    record.capability_id,
                    record.external_tool_name,
                    record.requester,
                    record.status.value,
                    record.duration_ms,
                    record.approval_id,
                    record.arguments_summary,
                    record.result_summary,
                    record.error_code,
                    record.error_message,
                    record.schema_hash,
                    record.started_at,
                    record.finished_at,
                ),
            )
        return record

    def list_calls(self, *, limit: int = 100, server_id: str | None = None) -> list[McpToolCallRecord]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if server_id:
                rows = conn.execute(
                    "SELECT * FROM mcp_tool_calls WHERE server_id = ? ORDER BY started_at DESC LIMIT ?",
                    (server_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mcp_tool_calls ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_call(row) for row in rows]

    def new_call_id(self) -> str:
        return str(uuid.uuid4())

    # --- row mappers ---

    @staticmethod
    def _row_to_config(row: sqlite3.Row) -> McpServerConfig:
        effects_raw = json.loads(row["semantic_effects_json"] or "{}")
        semantic: dict[str, tuple[str, ...]] = {}
        if isinstance(effects_raw, dict):
            for key, value in effects_raw.items():
                if isinstance(value, list):
                    semantic[str(key)] = tuple(str(v) for v in value)
        return McpServerConfig(
            server_id=row["server_id"],
            display_name=row["display_name"],
            source_kind=McpSourceKind(row["source_kind"]),
            source_key=row["source_key"],
            transport=McpTransportKind(row["transport"]),
            command=row["command"],
            args=tuple(json.loads(row["args_json"] or "[]")),
            url=row["url"],
            cwd=row["cwd"],
            env_public=dict(json.loads(row["env_public_json"] or "{}")),
            secret_refs=dict(json.loads(row["secret_refs_json"] or "{}")),
            timeout_seconds=float(row["timeout_seconds"]),
            enabled=bool(row["enabled"]),
            trust=McpTrust(row["trust"]),
            requested_isolation=McpIsolationKind(row["requested_isolation"]),
            max_concurrent_calls=int(row["max_concurrent_calls"]),
            owner_module_id=row["owner_module_id"],
            eager_connect=bool(row["eager_connect"]),
            expand_tools=bool(row["expand_tools"]),
            semantic_effects=semantic,
            metadata=dict(json.loads(row["metadata_json"] or "{}")),
        )

    @staticmethod
    def _row_to_tool(row: sqlite3.Row) -> McpToolRecord:
        return McpToolRecord(
            server_id=row["server_id"],
            external_name=row["external_name"],
            capability_id=row["capability_id"],
            description=row["description"] or "",
            input_schema=dict(json.loads(row["input_schema_json"] or "{}")),
            schema_hash=row["schema_hash"],
            semantic_effects=tuple(json.loads(row["semantic_effects_json"] or "[]")),
            availability=McpToolAvailability(row["availability"]),
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            server_version=row["server_version"],
            protocol_version=row["protocol_version"],
        )

    @staticmethod
    def _row_to_call(row: sqlite3.Row) -> McpToolCallRecord:
        return McpToolCallRecord(
            call_id=row["call_id"],
            trace_id=row["trace_id"],
            server_id=row["server_id"],
            capability_id=row["capability_id"],
            external_tool_name=row["external_tool_name"],
            requester=row["requester"],
            status=McpCallStatus(row["status"]),
            duration_ms=row["duration_ms"],
            approval_id=row["approval_id"],
            arguments_summary=row["arguments_summary"],
            result_summary=row["result_summary"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            schema_hash=row["schema_hash"],
        )
