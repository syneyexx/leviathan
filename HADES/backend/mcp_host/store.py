"""Persistence for managed MCP servers, tools, and executions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from mcp_host.protocol import export_safe_server, model_tool_name, redact_mapping, stable_tool_id, validate_input_schema


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_mcp_schema(db: sqlite3.Connection) -> None:
    """Additive migrations 15–16 — MCP management tables on the platform database.

    Executions intentionally have no FK CASCADE to mcp_servers so audit history
    survives server deletion (server_id remains as a historical reference).
    """
    now = _now()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            transport TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            auto_connect INTEGER NOT NULL DEFAULT 0,
            owner_kind TEXT NOT NULL DEFAULT 'managed',
            owner_plugin_id TEXT,
            catalog_id TEXT,
            command_json TEXT,
            env_json TEXT,
            endpoint_url TEXT,
            auth_method TEXT NOT NULL DEFAULT 'none',
            headers_json TEXT,
            auth_secret_ref TEXT,
            timeout_seconds REAL NOT NULL DEFAULT 60,
            connection_status TEXT NOT NULL DEFAULT 'configured',
            auth_status TEXT NOT NULL DEFAULT 'none',
            last_check_at TEXT,
            last_error TEXT,
            last_error_kind TEXT,
            protocol_version TEXT,
            discovery_complete INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mcp_tools (
            id TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            remote_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            description TEXT,
            input_schema_json TEXT,
            output_schema_json TEXT,
            annotations_json TEXT,
            allowed INTEGER NOT NULL DEFAULT 0,
            chatbot_enabled INTEGER NOT NULL DEFAULT 0,
            require_approval INTEGER NOT NULL DEFAULT 1,
            schema_issue TEXT,
            last_executed_at TEXT,
            last_result_status TEXT,
            discovered_at TEXT,
            updated_at TEXT,
            UNIQUE(server_id, remote_name),
            FOREIGN KEY(server_id) REFERENCES mcp_servers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mcp_executions (
            id TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            tool_id TEXT NOT NULL,
            tool_call_id TEXT,
            status TEXT NOT NULL,
            error_kind TEXT,
            started_at TEXT,
            ended_at TEXT,
            duration_ms REAL,
            input_json TEXT,
            result_json TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_mcp_tools_server ON mcp_tools(server_id);
        CREATE INDEX IF NOT EXISTS idx_mcp_exec_server ON mcp_executions(server_id);
        """
    )
    db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(15, ?)", (now,))

    # Migration 16: scoped idempotency + case-insensitive server name uniqueness.
    # Preserve existing execution history; rewrite global UNIQUE(idempotency_key).
    applied = {
        int(row[0])
        for row in db.execute("SELECT version FROM schema_migrations").fetchall()
        if row and row[0] is not None
    }
    if 16 not in applied:
        # Recover interrupted legacy rebuild remnants before attempting work.
        table_names = {
            str(row[0])
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "mcp_executions" not in table_names and "mcp_executions_v16" in table_names:
            db.execute("ALTER TABLE mcp_executions_v16 RENAME TO mcp_executions")
            table_names.add("mcp_executions")
            table_names.discard("mcp_executions_v16")
        if "mcp_executions" not in table_names and "mcp_executions_pre_v16" in table_names:
            db.execute("ALTER TABLE mcp_executions_pre_v16 RENAME TO mcp_executions")
            table_names.add("mcp_executions")
            table_names.discard("mcp_executions_pre_v16")
        if "mcp_executions" in table_names and "mcp_executions_v16" in table_names:
            # Copy completed but swap did not; discard the temporary rebuild table.
            db.execute("DROP TABLE mcp_executions_v16")
            table_names.discard("mcp_executions_v16")

        # Older DBs created with UNIQUE(idempotency_key) need a table rebuild.
        cols = {str(row[1]) for row in db.execute("PRAGMA table_info(mcp_executions)").fetchall()}
        index_rows = db.execute("PRAGMA index_list(mcp_executions)").fetchall()
        has_global_unique = False
        for idx in index_rows:
            # PRAGMA index_list: seq, name, unique, origin, partial
            if int(idx[2] or 0) != 1:
                continue
            idx_name = str(idx[1])
            idx_cols = [str(c[2]) for c in db.execute(f"PRAGMA index_info('{idx_name}')").fetchall()]
            if idx_cols == ["idempotency_key"]:
                has_global_unique = True
                break
        # Also detect UNIQUE constraint from CREATE TABLE (auto index).
        if not has_global_unique:
            for idx in index_rows:
                if int(idx[2] or 0) != 1:
                    continue
                idx_name = str(idx[1])
                idx_cols = [str(c[2]) for c in db.execute(f"PRAGMA index_info('{idx_name}')").fetchall()]
                if "idempotency_key" in idx_cols and len(idx_cols) == 1:
                    has_global_unique = True
                    break
        if has_global_unique or "idempotency_key" in cols:
            # Never DROP the live table before the replacement rename succeeds.
            # SQLite DDL is statement-autocommit; reorder so failures leave the
            # original mcp_executions intact (or recoverable via pre_v16 remnant).
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_executions_v16 (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    tool_call_id TEXT,
                    status TEXT NOT NULL,
                    error_kind TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    duration_ms REAL,
                    input_json TEXT,
                    result_json TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT
                )
                """
            )
            db.execute("DELETE FROM mcp_executions_v16")
            db.execute(
                """
                INSERT INTO mcp_executions_v16
                    SELECT id,server_id,tool_id,tool_call_id,status,error_kind,started_at,ended_at,
                           duration_ms,input_json,result_json,cancel_requested,idempotency_key
                    FROM mcp_executions
                """
            )
            try:
                db.execute("ALTER TABLE mcp_executions RENAME TO mcp_executions_pre_v16")
            except sqlite3.Error:
                db.execute("DROP TABLE IF EXISTS mcp_executions_v16")
                raise
            try:
                db.execute("ALTER TABLE mcp_executions_v16 RENAME TO mcp_executions")
            except sqlite3.Error:
                # Restore original name if the final rename fails.
                db.execute("ALTER TABLE mcp_executions_pre_v16 RENAME TO mcp_executions")
                db.execute("DROP TABLE IF EXISTS mcp_executions_v16")
                raise
            db.execute("DROP TABLE IF EXISTS mcp_executions_pre_v16")
            db.execute("CREATE INDEX IF NOT EXISTS idx_mcp_exec_server ON mcp_executions(server_id)")
        # Composite uniqueness: same user key may be reused across servers/tools,
        # but not for the same server+tool pair. NULL keys remain non-unique.
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_exec_idempotency_scope
            ON mcp_executions(server_id, tool_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_servers_name_nocase
            ON mcp_servers(name COLLATE NOCASE)
            """
        )
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(16, ?)", (now,))
    db.commit()


class McpStore:
    def __init__(self, platform_db: Any) -> None:
        self.platform_db = platform_db
        self._ensure()

    def _ensure(self) -> None:
        with self.platform_db.connection() as db:
            ensure_mcp_schema(db)

    @staticmethod
    def _loads(raw: str | None, fallback: Any) -> Any:
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    def _row_server(self, row: sqlite3.Row) -> dict[str, Any]:
        command = self._loads(row["command_json"], None)
        env = self._loads(row["env_json"], {"plain": {}, "secret_refs": {}})
        headers = self._loads(row["headers_json"], {})
        metadata = self._loads(row["metadata_json"], {})
        secret_refs = env.get("secret_refs") if isinstance(env, dict) else {}
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "transport": row["transport"],
            "enabled": bool(row["enabled"]),
            "auto_connect": bool(row["auto_connect"]),
            "owner_kind": row["owner_kind"],
            "owner_plugin_id": row["owner_plugin_id"],
            "catalog_id": row["catalog_id"],
            "command": command,
            "env": {
                "plain": (env.get("plain") if isinstance(env, dict) else {}) or {},
                "secret_refs": secret_refs or {},
                "secret_keys": sorted((secret_refs or {}).keys()),
            },
            "endpoint_url": row["endpoint_url"],
            "auth_method": row["auth_method"] or "none",
            "headers": headers if isinstance(headers, dict) else {},
            "auth_secret_ref": row["auth_secret_ref"],
            "has_auth_secret": bool(row["auth_secret_ref"]),
            "timeout_seconds": float(row["timeout_seconds"] or 60),
            "connection_status": row["connection_status"],
            "auth_status": row["auth_status"],
            "last_check_at": row["last_check_at"],
            "last_error": row["last_error"],
            "last_error_kind": row["last_error_kind"],
            "protocol_version": row["protocol_version"],
            "discovery_complete": bool(row["discovery_complete"]),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_servers(self) -> list[dict[str, Any]]:
        with self.platform_db.connection() as db:
            rows = db.execute("SELECT * FROM mcp_servers ORDER BY name COLLATE NOCASE").fetchall()
        return [self._row_server(row) for row in rows]

    def get_server(self, server_id: str) -> dict[str, Any] | None:
        with self.platform_db.connection() as db:
            row = db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,)).fetchone()
        return self._row_server(row) if row else None

    def get_server_by_name(self, name: str) -> dict[str, Any] | None:
        with self.platform_db.connection() as db:
            row = db.execute("SELECT * FROM mcp_servers WHERE lower(name)=lower(?)", (name,)).fetchone()
        return self._row_server(row) if row else None

    def get_server_by_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        with self.platform_db.connection() as db:
            row = db.execute(
                "SELECT * FROM mcp_servers WHERE owner_plugin_id=? AND owner_kind='plugin'",
                (plugin_id,),
            ).fetchone()
        return self._row_server(row) if row else None

    def upsert_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        server_id = str(payload.get("id") or uuid.uuid4().hex)
        existing = self.get_server(server_id)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("Servernaam is verplicht")
        conflict = self.get_server_by_name(name)
        if conflict and conflict["id"] != server_id:
            raise ValueError(f"Er bestaat al een MCP-server met naam '{name}'")

        command = payload.get("command")
        env = payload.get("env") if isinstance(payload.get("env"), dict) else {"plain": {}, "secret_refs": {}}
        headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        values = (
            server_id,
            name,
            str(payload.get("description") or ""),
            str(payload.get("transport") or "stdio"),
            1 if payload.get("enabled", True) else 0,
            1 if payload.get("auto_connect") else 0,
            str(payload.get("owner_kind") or "managed"),
            payload.get("owner_plugin_id"),
            payload.get("catalog_id"),
            json.dumps(command, ensure_ascii=False) if command is not None else None,
            json.dumps(
                {
                    "plain": env.get("plain") or {},
                    "secret_refs": env.get("secret_refs") or {},
                },
                ensure_ascii=False,
            ),
            payload.get("endpoint_url"),
            str(payload.get("auth_method") or "none"),
            json.dumps(headers, ensure_ascii=False),
            payload.get("auth_secret_ref") if "auth_secret_ref" in payload else (existing or {}).get("auth_secret_ref"),
            float(payload.get("timeout_seconds") or 60),
            str(payload.get("connection_status") or (existing or {}).get("connection_status") or "configured"),
            str(payload.get("auth_status") or (existing or {}).get("auth_status") or "none"),
            payload.get("last_check_at", (existing or {}).get("last_check_at")),
            payload.get("last_error", (existing or {}).get("last_error")),
            payload.get("last_error_kind", (existing or {}).get("last_error_kind")),
            payload.get("protocol_version", (existing or {}).get("protocol_version")),
            1 if payload.get("discovery_complete", (existing or {}).get("discovery_complete")) else 0,
            json.dumps(metadata, ensure_ascii=False),
            (existing or {}).get("created_at") or now,
            now,
        )
        with self.platform_db.connection() as db:
            db.execute(
                """
                INSERT INTO mcp_servers(
                    id,name,description,transport,enabled,auto_connect,owner_kind,owner_plugin_id,catalog_id,
                    command_json,env_json,endpoint_url,auth_method,headers_json,auth_secret_ref,timeout_seconds,
                    connection_status,auth_status,last_check_at,last_error,last_error_kind,protocol_version,
                    discovery_complete,metadata_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    transport=excluded.transport,
                    enabled=excluded.enabled,
                    auto_connect=excluded.auto_connect,
                    owner_kind=excluded.owner_kind,
                    owner_plugin_id=excluded.owner_plugin_id,
                    catalog_id=excluded.catalog_id,
                    command_json=excluded.command_json,
                    env_json=excluded.env_json,
                    endpoint_url=excluded.endpoint_url,
                    auth_method=excluded.auth_method,
                    headers_json=excluded.headers_json,
                    auth_secret_ref=excluded.auth_secret_ref,
                    timeout_seconds=excluded.timeout_seconds,
                    connection_status=excluded.connection_status,
                    auth_status=excluded.auth_status,
                    last_check_at=excluded.last_check_at,
                    last_error=excluded.last_error,
                    last_error_kind=excluded.last_error_kind,
                    protocol_version=excluded.protocol_version,
                    discovery_complete=excluded.discovery_complete,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                values,
            )
            db.commit()
        return self.get_server(server_id)  # type: ignore[return-value]

    def update_server_status(
        self,
        server_id: str,
        *,
        connection_status: str | None = None,
        auth_status: str | None = None,
        last_error: str | None = None,
        last_error_kind: str | None = None,
        protocol_version: str | None = None,
        discovery_complete: bool | None = None,
        touch_check: bool = False,
        clear_error: bool = False,
    ) -> dict[str, Any] | None:
        server = self.get_server(server_id)
        if not server:
            return None
        patch = dict(server)
        if connection_status is not None:
            patch["connection_status"] = connection_status
        if auth_status is not None:
            patch["auth_status"] = auth_status
        if clear_error:
            patch["last_error"] = None
            patch["last_error_kind"] = None
        if last_error is not None:
            patch["last_error"] = last_error
        if last_error_kind is not None:
            patch["last_error_kind"] = last_error_kind
        if protocol_version is not None:
            patch["protocol_version"] = protocol_version
        if discovery_complete is not None:
            patch["discovery_complete"] = discovery_complete
        if touch_check:
            patch["last_check_at"] = _now()
        # Preserve env secret_refs shape for upsert
        env = server.get("env") or {}
        patch["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
        return self.upsert_server(patch)

    def delete_server(self, server_id: str) -> bool:
        with self.platform_db.connection() as db:
            cur = db.execute("DELETE FROM mcp_servers WHERE id=?", (server_id,))
            db.execute("DELETE FROM mcp_tools WHERE server_id=?", (server_id,))
            db.commit()
            return cur.rowcount > 0

    def _row_tool(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "server_id": row["server_id"],
            "remote_name": row["remote_name"],
            "model_name": row["model_name"],
            "description": row["description"] or "",
            "input_schema": self._loads(row["input_schema_json"], {}),
            "output_schema": self._loads(row["output_schema_json"], None),
            "annotations": self._loads(row["annotations_json"], {}),
            "allowed": bool(row["allowed"]),
            "chatbot_enabled": bool(row["chatbot_enabled"]),
            "require_approval": bool(row["require_approval"]),
            "schema_issue": row["schema_issue"],
            "last_executed_at": row["last_executed_at"],
            "last_result_status": row["last_result_status"],
            "discovered_at": row["discovered_at"],
            "updated_at": row["updated_at"],
        }

    def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        with self.platform_db.connection() as db:
            if server_id:
                rows = db.execute(
                    "SELECT * FROM mcp_tools WHERE server_id=? ORDER BY remote_name COLLATE NOCASE",
                    (server_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM mcp_tools ORDER BY server_id, remote_name COLLATE NOCASE").fetchall()
        return [self._row_tool(row) for row in rows]

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:
        with self.platform_db.connection() as db:
            row = db.execute("SELECT * FROM mcp_tools WHERE id=?", (tool_id,)).fetchone()
        return self._row_tool(row) if row else None

    def replace_discovered_tools(self, server_id: str, remote_tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Update discovery: add/update tools; remove missing; never expand rights on new tools."""
        now = _now()
        existing = {t["remote_name"]: t for t in self.list_tools(server_id)}
        seen: set[str] = set()
        added = 0
        updated = 0
        with self.platform_db.connection() as db:
            for remote in remote_tools:
                if not isinstance(remote, dict):
                    continue
                remote_name = str(remote.get("name") or "").strip()
                if not remote_name:
                    continue
                seen.add(remote_name)
                tool_id = stable_tool_id(server_id, remote_name)
                input_schema = remote.get("inputSchema") if isinstance(remote.get("inputSchema"), dict) else remote.get("input_schema")
                if not isinstance(input_schema, dict):
                    input_schema = {"type": "object", "properties": {}}
                output_schema = remote.get("outputSchema") if isinstance(remote.get("outputSchema"), dict) else remote.get("output_schema")
                annotations = remote.get("annotations") if isinstance(remote.get("annotations"), dict) else {}
                schema_issue = validate_input_schema(input_schema)
                prev = existing.get(remote_name)
                # New tools: no autonomous rights by default.
                allowed = bool(prev["allowed"]) if prev else False
                chatbot_enabled = bool(prev["chatbot_enabled"]) if prev else False
                require_approval = bool(prev["require_approval"]) if prev else True
                if prev:
                    updated += 1
                else:
                    added += 1
                db.execute(
                    """
                    INSERT INTO mcp_tools(
                        id,server_id,remote_name,model_name,description,input_schema_json,output_schema_json,
                        annotations_json,allowed,chatbot_enabled,require_approval,schema_issue,
                        last_executed_at,last_result_status,discovered_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        model_name=excluded.model_name,
                        description=excluded.description,
                        input_schema_json=excluded.input_schema_json,
                        output_schema_json=excluded.output_schema_json,
                        annotations_json=excluded.annotations_json,
                        schema_issue=excluded.schema_issue,
                        updated_at=excluded.updated_at
                    """,
                    (
                        tool_id,
                        server_id,
                        remote_name,
                        model_tool_name(server_id, remote_name),
                        str(remote.get("description") or remote_name),
                        json.dumps(input_schema, ensure_ascii=False),
                        json.dumps(output_schema, ensure_ascii=False) if output_schema is not None else None,
                        json.dumps(annotations, ensure_ascii=False),
                        1 if allowed else 0,
                        1 if chatbot_enabled else 0,
                        1 if require_approval else 0,
                        schema_issue,
                        (prev or {}).get("last_executed_at"),
                        (prev or {}).get("last_result_status"),
                        (prev or {}).get("discovered_at") or now,
                        now,
                    ),
                )
            removed = 0
            for remote_name, prev in existing.items():
                if remote_name not in seen:
                    db.execute("DELETE FROM mcp_tools WHERE id=?", (prev["id"],))
                    removed += 1
            db.commit()
        return {"added": added, "updated": updated, "removed": removed, "total": len(seen)}

    def update_tool_prefs(self, tool_id: str, prefs: dict[str, Any]) -> dict[str, Any] | None:
        tool = self.get_tool(tool_id)
        if not tool:
            return None
        allowed = prefs.get("allowed", tool["allowed"])
        chatbot_enabled = prefs.get("chatbot_enabled", tool["chatbot_enabled"])
        require_approval = prefs.get("require_approval", tool["require_approval"])
        # chatbot_enabled is shortlist/visibility only — never force-allow execution.
        # Catalog shortlists already require both chatbot_enabled AND allowed.
        with self.platform_db.connection() as db:
            db.execute(
                """
                UPDATE mcp_tools
                SET allowed=?, chatbot_enabled=?, require_approval=?, updated_at=?
                WHERE id=?
                """,
                (1 if allowed else 0, 1 if chatbot_enabled else 0, 1 if require_approval else 0, _now(), tool_id),
            )
            db.commit()
        return self.get_tool(tool_id)

    def mark_tool_execution(self, tool_id: str, status: str) -> None:
        with self.platform_db.connection() as db:
            db.execute(
                "UPDATE mcp_tools SET last_executed_at=?, last_result_status=?, updated_at=? WHERE id=?",
                (_now(), status, _now(), tool_id),
            )
            db.commit()

    def create_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        exec_id = str(payload.get("id") or uuid.uuid4().hex)
        idem = payload.get("idempotency_key")
        server_id = payload["server_id"]
        tool_id = payload["tool_id"]
        with self.platform_db.connection() as db:
            if idem:
                existing = db.execute(
                    """
                    SELECT * FROM mcp_executions
                    WHERE server_id=? AND tool_id=? AND idempotency_key=?
                    """,
                    (server_id, tool_id, idem),
                ).fetchone()
                if existing:
                    return self._row_execution(existing)
            db.execute(
                """
                INSERT INTO mcp_executions(
                    id,server_id,tool_id,tool_call_id,status,error_kind,started_at,ended_at,duration_ms,
                    input_json,result_json,cancel_requested,idempotency_key
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    exec_id,
                    server_id,
                    tool_id,
                    payload.get("tool_call_id"),
                    payload.get("status") or "running",
                    payload.get("error_kind"),
                    payload.get("started_at") or _now(),
                    payload.get("ended_at"),
                    payload.get("duration_ms"),
                    json.dumps(redact_mapping(payload.get("input") or {}), ensure_ascii=False),
                    json.dumps(redact_mapping(payload.get("result") or {}), ensure_ascii=False)
                    if payload.get("result") is not None
                    else None,
                    1 if payload.get("cancel_requested") else 0,
                    idem,
                ),
            )
            db.commit()
            row = db.execute("SELECT * FROM mcp_executions WHERE id=?", (exec_id,)).fetchone()
        return self._row_execution(row)

    def _row_execution(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "server_id": row["server_id"],
            "tool_id": row["tool_id"],
            "tool_call_id": row["tool_call_id"],
            "status": row["status"],
            "error_kind": row["error_kind"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "duration_ms": row["duration_ms"],
            "input": self._loads(row["input_json"], {}),
            "result": self._loads(row["result_json"], None),
            "cancel_requested": bool(row["cancel_requested"]),
            "idempotency_key": row["idempotency_key"],
        }

    def finish_execution(self, exec_id: str, *, status: str, result: Any = None, error_kind: str | None = None) -> dict[str, Any] | None:
        with self.platform_db.connection() as db:
            row = db.execute("SELECT * FROM mcp_executions WHERE id=?", (exec_id,)).fetchone()
            if not row:
                return None
            started = row["started_at"]
            ended = _now()
            duration = None
            try:
                start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                duration = (datetime.now(UTC) - start_dt).total_seconds() * 1000.0
            except Exception:
                duration = None
            db.execute(
                """
                UPDATE mcp_executions
                SET status=?, error_kind=?, ended_at=?, duration_ms=?, result_json=?
                WHERE id=?
                """,
                (
                    status,
                    error_kind,
                    ended,
                    duration,
                    json.dumps(redact_mapping(result or {}), ensure_ascii=False),
                    exec_id,
                ),
            )
            db.commit()
            row = db.execute("SELECT * FROM mcp_executions WHERE id=?", (exec_id,)).fetchone()
        return self._row_execution(row)

    def request_cancel(self, exec_id: str) -> dict[str, Any] | None:
        with self.platform_db.connection() as db:
            db.execute("UPDATE mcp_executions SET cancel_requested=1 WHERE id=? AND status='running'", (exec_id,))
            db.commit()
            row = db.execute("SELECT * FROM mcp_executions WHERE id=?", (exec_id,)).fetchone()
        return self._row_execution(row) if row else None

    def list_executions(self, *, server_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.platform_db.connection() as db:
            if server_id:
                rows = db.execute(
                    "SELECT * FROM mcp_executions WHERE server_id=? ORDER BY started_at DESC LIMIT ?",
                    (server_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM mcp_executions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_execution(row) for row in rows]

    def export_servers(self) -> list[dict[str, Any]]:
        return [export_safe_server(server) for server in self.list_servers()]
