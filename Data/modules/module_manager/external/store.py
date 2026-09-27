"""CONTROL persistence for external capability runtime metadata.

Does not invent a fourth database. Tables live on the Control Plane DB.
Persisted ENABLED/RUNNING is never treated as live readiness — callers must reconcile.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExternalCapabilityStore:
    """Durable CONTROL store for external modules, versions, skills, plugin bindings."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
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
            CREATE TABLE IF NOT EXISTS external_modules (
                module_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                adapter TEXT NOT NULL,
                source_json TEXT NOT NULL DEFAULT '{}',
                desired_state TEXT NOT NULL DEFAULT 'STOPPED',
                runtime_state TEXT NOT NULL DEFAULT 'DISCOVERED',
                active_version_id TEXT,
                last_error TEXT,
                last_used_at TEXT,
                capability_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS external_module_versions (
                version_id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL,
                source_ref TEXT,
                resolved_commit TEXT,
                content_hash TEXT,
                install_root TEXT NOT NULL,
                install_strategy_json TEXT NOT NULL DEFAULT '[]',
                dependency_versions_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'INSTALLED',
                installed_at TEXT NOT NULL,
                activated_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(module_id) REFERENCES external_modules(module_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ext_versions_module
                ON external_module_versions(module_id, installed_at DESC);

            CREATE TABLE IF NOT EXISTS external_process_records (
                module_id TEXT PRIMARY KEY,
                pid INTEGER,
                fingerprint TEXT,
                command_json TEXT NOT NULL DEFAULT '[]',
                cwd TEXT,
                started_at TEXT,
                exit_code INTEGER,
                restart_count INTEGER NOT NULL DEFAULT 0,
                health TEXT NOT NULL DEFAULT 'UNKNOWN',
                stdout_artifact TEXT,
                stderr_artifact TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(module_id) REFERENCES external_modules(module_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS external_skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_repo TEXT,
                source_path TEXT,
                source_ref TEXT,
                version TEXT,
                content_hash TEXT NOT NULL,
                instruction_artifact TEXT,
                resource_refs_json TEXT NOT NULL DEFAULT '[]',
                script_refs_json TEXT NOT NULL DEFAULT '[]',
                required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                trigger_description TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                catalog_only INTEGER NOT NULL DEFAULT 0,
                module_id TEXT,
                imported_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(name, source_repo, content_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_ext_skills_name ON external_skills(name);
            CREATE INDEX IF NOT EXISTS idx_ext_skills_enabled ON external_skills(enabled, catalog_only);

            CREATE TABLE IF NOT EXISTS external_skill_catalogs (
                catalog_id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL,
                source TEXT NOT NULL,
                entry_count INTEGER NOT NULL DEFAULT 0,
                last_refreshed_at TEXT,
                index_artifact TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(module_id) REFERENCES external_modules(module_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS external_plugin_bindings (
                plugin_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '0.0.0',
                bindings_json TEXT NOT NULL DEFAULT '[]',
                endpoint TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS external_log_windows (
                module_id TEXT PRIMARY KEY,
                lines_json TEXT NOT NULL DEFAULT '[]',
                byte_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )

    # --- modules ---

    def upsert_module(
        self,
        *,
        module_id: str,
        name: str,
        adapter: str,
        source: dict[str, Any] | None = None,
        desired_state: str = "STOPPED",
        runtime_state: str = "DISCOVERED",
        active_version_id: str | None = None,
        last_error: str | None = None,
        capability_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT created_at FROM external_modules WHERE module_id = ?",
                (module_id,),
            ).fetchone()
            created = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO external_modules(
                    module_id, name, adapter, source_json, desired_state, runtime_state,
                    active_version_id, last_error, capability_count, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(module_id) DO UPDATE SET
                    name=excluded.name,
                    adapter=excluded.adapter,
                    source_json=excluded.source_json,
                    desired_state=excluded.desired_state,
                    runtime_state=excluded.runtime_state,
                    active_version_id=COALESCE(excluded.active_version_id, external_modules.active_version_id),
                    last_error=excluded.last_error,
                    capability_count=excluded.capability_count,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    module_id,
                    name,
                    adapter,
                    json.dumps(source or {}, separators=(",", ":")),
                    desired_state,
                    runtime_state,
                    active_version_id,
                    last_error,
                    int(capability_count),
                    json.dumps(metadata or {}, separators=(",", ":")),
                    created,
                    now,
                ),
            )
        return self.get_module(module_id) or {}

    def set_runtime_state(
        self,
        module_id: str,
        runtime_state: str,
        *,
        last_error: str | None = None,
        desired_state: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            if desired_state is None:
                conn.execute(
                    """
                    UPDATE external_modules
                    SET runtime_state = ?, last_error = ?, updated_at = ?
                    WHERE module_id = ?
                    """,
                    (runtime_state, last_error, now, module_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE external_modules
                    SET runtime_state = ?, last_error = ?, desired_state = ?, updated_at = ?
                    WHERE module_id = ?
                    """,
                    (runtime_state, last_error, desired_state, now, module_id),
                )

    def touch_used(self, module_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE external_modules SET last_used_at = ?, updated_at = ? WHERE module_id = ?",
                (now, now, module_id),
            )

    def get_module(self, module_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM external_modules WHERE module_id = ?",
                (module_id,),
            ).fetchone()
            return self._module_row(row) if row else None

    def list_modules(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM external_modules ORDER BY module_id"
            ).fetchall()
            return [self._module_row(r) for r in rows]

    def _module_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "module_id": row["module_id"],
            "name": row["name"],
            "adapter": row["adapter"],
            "source": json.loads(row["source_json"] or "{}"),
            "desired_state": row["desired_state"],
            "runtime_state": row["runtime_state"],
            "active_version_id": row["active_version_id"],
            "last_error": row["last_error"],
            "last_used_at": row["last_used_at"],
            "capability_count": int(row["capability_count"] or 0),
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "truth": {
                "persisted_runtime_state_is_not_live_health": True,
            },
        }

    # --- versions ---

    def add_version(
        self,
        *,
        version_id: str,
        module_id: str,
        install_root: str,
        source_ref: str | None = None,
        resolved_commit: str | None = None,
        content_hash: str | None = None,
        install_strategies: list[str] | None = None,
        dependency_versions: dict[str, Any] | None = None,
        status: str = "INSTALLED",
        metadata: dict[str, Any] | None = None,
        activate: bool = False,
        adapter: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        # Ensure parent module row exists (FK) without requiring callers to pre-register.
        if self.get_module(module_id) is None:
            self.upsert_module(
                module_id=module_id,
                name=name or module_id,
                adapter=adapter or "EXTERNAL",
                source={"install_root": install_root, "source_ref": source_ref},
                desired_state="STOPPED",
                runtime_state="INSTALLED" if activate else "DISCOVERED",
            )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO external_module_versions(
                    version_id, module_id, source_ref, resolved_commit, content_hash,
                    install_root, install_strategy_json, dependency_versions_json,
                    status, installed_at, activated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version_id) DO UPDATE SET
                    status=excluded.status,
                    metadata_json=excluded.metadata_json
                """,
                (
                    version_id,
                    module_id,
                    source_ref,
                    resolved_commit,
                    content_hash,
                    install_root,
                    json.dumps(install_strategies or [], separators=(",", ":")),
                    json.dumps(dependency_versions or {}, separators=(",", ":")),
                    status,
                    now,
                    now if activate else None,
                    json.dumps(metadata or {}, separators=(",", ":")),
                ),
            )
            if activate:
                conn.execute(
                    """
                    UPDATE external_modules
                    SET active_version_id = ?, runtime_state = 'INSTALLED', updated_at = ?
                    WHERE module_id = ?
                    """,
                    (version_id, now, module_id),
                )
        return self.get_version(version_id) or {}

    def activate_version(self, module_id: str, version_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE external_module_versions SET activated_at = ?, status = 'ACTIVE' WHERE version_id = ?",
                (now, version_id),
            )
            conn.execute(
                """
                UPDATE external_modules
                SET active_version_id = ?, updated_at = ?
                WHERE module_id = ?
                """,
                (version_id, now, module_id),
            )

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM external_module_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            return self._version_row(row) if row else None

    def list_versions(self, module_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM external_module_versions
                WHERE module_id = ?
                ORDER BY installed_at DESC
                """,
                (module_id,),
            ).fetchall()
            return [self._version_row(r) for r in rows]

    def get_active_version(self, module_id: str) -> dict[str, Any] | None:
        mod = self.get_module(module_id)
        if not mod or not mod.get("active_version_id"):
            return None
        return self.get_version(str(mod["active_version_id"]))

    def _version_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "version_id": row["version_id"],
            "module_id": row["module_id"],
            "source_ref": row["source_ref"],
            "resolved_commit": row["resolved_commit"],
            "content_hash": row["content_hash"],
            "install_root": row["install_root"],
            "install_strategies": json.loads(row["install_strategy_json"] or "[]"),
            "dependency_versions": json.loads(row["dependency_versions_json"] or "{}"),
            "status": row["status"],
            "installed_at": row["installed_at"],
            "activated_at": row["activated_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    # --- process records ---

    def upsert_process(
        self,
        *,
        module_id: str,
        pid: int | None = None,
        fingerprint: str | None = None,
        command: list[str] | None = None,
        cwd: str | None = None,
        started_at: str | None = None,
        exit_code: int | None = None,
        restart_count: int = 0,
        health: str = "UNKNOWN",
        stdout_artifact: str | None = None,
        stderr_artifact: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO external_process_records(
                    module_id, pid, fingerprint, command_json, cwd, started_at,
                    exit_code, restart_count, health, stdout_artifact, stderr_artifact,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(module_id) DO UPDATE SET
                    pid=excluded.pid,
                    fingerprint=excluded.fingerprint,
                    command_json=excluded.command_json,
                    cwd=excluded.cwd,
                    started_at=excluded.started_at,
                    exit_code=excluded.exit_code,
                    restart_count=excluded.restart_count,
                    health=excluded.health,
                    stdout_artifact=excluded.stdout_artifact,
                    stderr_artifact=excluded.stderr_artifact,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    module_id,
                    pid,
                    fingerprint,
                    json.dumps(command or [], separators=(",", ":")),
                    cwd,
                    started_at,
                    exit_code,
                    int(restart_count),
                    health,
                    stdout_artifact,
                    stderr_artifact,
                    json.dumps(metadata or {}, separators=(",", ":")),
                    now,
                ),
            )

    def get_process(self, module_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM external_process_records WHERE module_id = ?",
                (module_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "module_id": row["module_id"],
                "pid": row["pid"],
                "fingerprint": row["fingerprint"],
                "command": json.loads(row["command_json"] or "[]"),
                "cwd": row["cwd"],
                "started_at": row["started_at"],
                "exit_code": row["exit_code"],
                "restart_count": int(row["restart_count"] or 0),
                "health": row["health"],
                "stdout_artifact": row["stdout_artifact"],
                "stderr_artifact": row["stderr_artifact"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "updated_at": row["updated_at"],
                "truth": {"persisted_pid_must_be_reconciled": True},
            }

    def clear_process(self, module_id: str) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM external_process_records WHERE module_id = ?", (module_id,))

    # --- skills ---

    def upsert_skill(self, record: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO external_skills(
                    skill_id, name, description, source_repo, source_path, source_ref,
                    version, content_hash, instruction_artifact, resource_refs_json,
                    script_refs_json, required_capabilities_json, trigger_description,
                    enabled, catalog_only, module_id, imported_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    source_ref=excluded.source_ref,
                    version=excluded.version,
                    content_hash=excluded.content_hash,
                    instruction_artifact=excluded.instruction_artifact,
                    resource_refs_json=excluded.resource_refs_json,
                    script_refs_json=excluded.script_refs_json,
                    required_capabilities_json=excluded.required_capabilities_json,
                    trigger_description=excluded.trigger_description,
                    enabled=excluded.enabled,
                    catalog_only=excluded.catalog_only,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record["skill_id"],
                    record["name"],
                    record.get("description") or "",
                    record.get("source_repo"),
                    record.get("source_path"),
                    record.get("source_ref"),
                    record.get("version"),
                    record["content_hash"],
                    record.get("instruction_artifact"),
                    json.dumps(record.get("resource_refs") or [], separators=(",", ":")),
                    json.dumps(record.get("script_refs") or [], separators=(",", ":")),
                    json.dumps(record.get("required_capabilities") or [], separators=(",", ":")),
                    record.get("trigger_description"),
                    1 if record.get("enabled", True) else 0,
                    1 if record.get("catalog_only", False) else 0,
                    record.get("module_id"),
                    record.get("imported_at") or now,
                    json.dumps(record.get("metadata") or {}, separators=(",", ":")),
                ),
            )
        return self.get_skill(record["skill_id"]) or record

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM external_skills WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            return self._skill_row(row) if row else None

    def search_skills(
        self,
        *,
        query: str | None = None,
        enabled_only: bool = True,
        include_catalog: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        clauses = ["1=1"]
        params: list[Any] = []
        if enabled_only:
            clauses.append("enabled = 1")
        if not include_catalog:
            clauses.append("catalog_only = 0")
        if query:
            clauses.append("(name LIKE ? OR description LIKE ? OR trigger_description LIKE ?)")
            q = f"%{query}%"
            params.extend([q, q, q])
        sql = (
            f"SELECT * FROM external_skills WHERE {' AND '.join(clauses)} "
            f"ORDER BY name LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(sql, params).fetchall()
            return [self._skill_row(r) for r in rows]

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE external_skills SET enabled = ? WHERE skill_id = ?",
                (1 if enabled else 0, skill_id),
            )
        return self.get_skill(skill_id)

    def count_skills(self, *, catalog_only: bool | None = None) -> int:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if catalog_only is None:
                row = conn.execute("SELECT COUNT(*) AS c FROM external_skills").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM external_skills WHERE catalog_only = ?",
                    (1 if catalog_only else 0,),
                ).fetchone()
            return int(row["c"] if row else 0)

    def _skill_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "skill_id": row["skill_id"],
            "name": row["name"],
            "description": row["description"],
            "source_repo": row["source_repo"],
            "source_path": row["source_path"],
            "source_ref": row["source_ref"],
            "version": row["version"],
            "content_hash": row["content_hash"],
            "instruction_artifact": row["instruction_artifact"],
            "resource_refs": json.loads(row["resource_refs_json"] or "[]"),
            "script_refs": json.loads(row["script_refs_json"] or "[]"),
            "required_capabilities": json.loads(row["required_capabilities_json"] or "[]"),
            "trigger_description": row["trigger_description"],
            "enabled": bool(row["enabled"]),
            "catalog_only": bool(row["catalog_only"]),
            "module_id": row["module_id"],
            "imported_at": row["imported_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    # --- plugin bindings persistence ---

    def upsert_plugin_binding(self, record: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO external_plugin_bindings(
                    plugin_id, name, kind, status, version, bindings_json,
                    endpoint, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plugin_id) DO UPDATE SET
                    name=excluded.name,
                    kind=excluded.kind,
                    status=excluded.status,
                    version=excluded.version,
                    bindings_json=excluded.bindings_json,
                    endpoint=excluded.endpoint,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record["plugin_id"],
                    record["name"],
                    record["kind"],
                    record["status"],
                    record.get("version") or "0.0.0",
                    json.dumps(record.get("bindings") or [], separators=(",", ":")),
                    record.get("endpoint"),
                    json.dumps(record.get("metadata") or {}, separators=(",", ":")),
                    now,
                ),
            )

    def list_plugin_bindings(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM external_plugin_bindings ORDER BY plugin_id"
            ).fetchall()
            return [
                {
                    "plugin_id": r["plugin_id"],
                    "name": r["name"],
                    "kind": r["kind"],
                    "status": r["status"],
                    "version": r["version"],
                    "bindings": json.loads(r["bindings_json"] or "[]"),
                    "endpoint": r["endpoint"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                    "updated_at": r["updated_at"],
                    "truth": {"persisted_enabled_is_not_runtime_ready": True},
                }
                for r in rows
            ]

    def delete_plugin_binding(self, plugin_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                "DELETE FROM external_plugin_bindings WHERE plugin_id = ?",
                (plugin_id,),
            )
            return cur.rowcount > 0

    # --- bounded log windows ---

    def append_logs(self, module_id: str, lines: list[str], *, max_lines: int = 500, max_bytes: int = 256_000) -> None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT lines_json, byte_count FROM external_log_windows WHERE module_id = ?",
                (module_id,),
            ).fetchone()
            existing = json.loads(row["lines_json"]) if row else []
            existing.extend(lines)
            # Bound by line count then by approximate bytes.
            if len(existing) > max_lines:
                existing = existing[-max_lines:]
            encoded = json.dumps(existing, separators=(",", ":"))
            while len(encoded.encode("utf-8")) > max_bytes and existing:
                existing = existing[1:]
                encoded = json.dumps(existing, separators=(",", ":"))
            conn.execute(
                """
                INSERT INTO external_log_windows(module_id, lines_json, byte_count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(module_id) DO UPDATE SET
                    lines_json=excluded.lines_json,
                    byte_count=excluded.byte_count,
                    updated_at=excluded.updated_at
                """,
                (module_id, encoded, len(encoded.encode("utf-8")), now),
            )

    def get_logs(self, module_id: str, *, limit: int = 200) -> list[str]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT lines_json FROM external_log_windows WHERE module_id = ?",
                (module_id,),
            ).fetchone()
            if not row:
                return []
            lines = json.loads(row["lines_json"] or "[]")
            return list(lines)[-max(1, min(int(limit), 500)) :]
