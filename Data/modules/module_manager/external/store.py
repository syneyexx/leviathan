"""CONTROL persistence for external capability runtime metadata.

Does not invent a fourth database. Tables live on the Control Plane DB.
Persisted ENABLED/RUNNING is never treated as live readiness — callers must reconcile.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Terminal install-operation statuses — used for active-idempotency uniqueness.
_TERMINAL_INSTALL_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED", "READY"}
)


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

            CREATE TABLE IF NOT EXISTS external_install_operations (
                operation_id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL,
                requested_ref TEXT,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                progress REAL,
                job_id TEXT,
                approval_id TEXT,
                plan_hash TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                package_manager TEXT,
                error_code TEXT,
                error_detail TEXT,
                retryable INTEGER NOT NULL DEFAULT 0,
                rollback_status TEXT,
                idempotency_key TEXT,
                started_at TEXT,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(module_id) REFERENCES external_modules(module_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ext_install_ops_module
                ON external_install_operations(module_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ext_install_ops_status
                ON external_install_operations(status);
            CREATE INDEX IF NOT EXISTS idx_ext_install_ops_job
                ON external_install_operations(job_id);
            CREATE INDEX IF NOT EXISTS idx_ext_install_ops_idempotency
                ON external_install_operations(idempotency_key);
            -- Prevent two equivalent ACTIVE installs for the same idempotency key.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_install_ops_active_idempotency
                ON external_install_operations(idempotency_key)
                WHERE idempotency_key IS NOT NULL
                  AND status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'COMPLETED', 'READY');

            CREATE TABLE IF NOT EXISTS external_install_dependency_receipts (
                receipt_id TEXT PRIMARY KEY,
                operation_id TEXT NOT NULL,
                dependency_id TEXT NOT NULL,
                state_before TEXT,
                state_after TEXT,
                package_manager TEXT,
                packages_json TEXT NOT NULL DEFAULT '[]',
                observed_version_before TEXT,
                observed_version_after TEXT,
                newly_installed INTEGER NOT NULL DEFAULT 0,
                command_fingerprint TEXT,
                started_at TEXT,
                completed_at TEXT,
                status TEXT NOT NULL,
                error_code TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(operation_id) REFERENCES external_install_operations(operation_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ext_install_receipts_operation
                ON external_install_dependency_receipts(operation_id);
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
        classification: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        class_key = (classification or "").strip().lower() or None
        if class_key == "agent":
            # Cognition agent SkillLibrary is not projected into external_skills.
            return []

        clauses = ["1=1"]
        params: list[Any] = []

        if enabled_only:
            clauses.append("enabled = 1")

        if class_key in {"core", "installed"}:
            clauses.append("catalog_only = 0")
        elif class_key in {"external", "catalog"}:
            clauses.append("catalog_only = 1")
        elif class_key == "tools":
            clauses.append(
                "script_refs_json IS NOT NULL AND script_refs_json NOT IN ('[]', 'null', '')"
            )
            if not include_catalog:
                clauses.append("catalog_only = 0")
        elif not include_catalog:
            clauses.append("catalog_only = 0")

        if query:
            # Tokenize natural-language goals so "Audit this Cloudflare Worker"
            # matches description/trigger text (not one giant LIKE phrase).
            tokens = [
                t.lower()
                for t in "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in str(query)).split()
                if len(t) >= 3
            ]
            # Drop ultra-common fillers that would over-match.
            stop = {
                "the",
                "this",
                "that",
                "with",
                "from",
                "using",
                "into",
                "for",
                "and",
                "are",
                "was",
                "you",
                "your",
                "please",
                "make",
                "create",
                "build",
                "use",
            }
            tokens = [t for t in tokens if t not in stop][:8]
            if tokens:
                token_clauses = []
                for tok in tokens:
                    token_clauses.append(
                        "(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(trigger_description) LIKE ?)"
                    )
                    q = f"%{tok}%"
                    params.extend([q, q, q])
                # OR across tokens — any strong keyword hit is enough for shortlist.
                clauses.append("(" + " OR ".join(token_clauses) + ")")
            else:
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

    def count_skills_available(self) -> int:
        """Enabled installed skills (usable by CapabilityBroker shortlist)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM external_skills WHERE enabled = 1 AND catalog_only = 0"
            ).fetchone()
            return int(row["c"] if row else 0)

    def count_distinct_skill_modules(self) -> int:
        """Distinct owning module_ids referenced by skill rows."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COUNT(DISTINCT module_id) AS c FROM external_skills "
                "WHERE module_id IS NOT NULL AND TRIM(module_id) != ''"
            ).fetchone()
            return int(row["c"] if row else 0)

    def count_skills_with_scripts(self, *, include_catalog: bool = True) -> int:
        with self.connect() as conn:
            self._ensure_schema(conn)
            clause = "script_refs_json IS NOT NULL AND script_refs_json NOT IN ('[]', 'null', '')"
            if not include_catalog:
                clause += " AND catalog_only = 0"
            row = conn.execute(f"SELECT COUNT(*) AS c FROM external_skills WHERE {clause}").fetchone()
            return int(row["c"] if row else 0)

    def count_skill_issues(self) -> int:
        """Installed skills missing a resolvable source_path (metadata integrity issue)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM external_skills WHERE catalog_only = 0 "
                "AND (source_path IS NULL OR TRIM(source_path) = '')"
            ).fetchone()
            return int(row["c"] if row else 0)

    def skill_totals_projection(self) -> dict[str, Any]:
        """Deterministic KPI / filter counts. Unmeasurable fields are explicit nulls."""
        installed = self.count_skills(catalog_only=False)
        catalog = self.count_skills(catalog_only=True)
        return {
            "installed": installed,
            "catalog": catalog,
            "total": installed + catalog,
            "available": self.count_skills_available(),
            "external_packs": self.count_distinct_skill_modules(),
            "tools": self.count_skills_with_scripts(include_catalog=True),
            "issues": self.count_skill_issues(),
            # Cognition agent SkillLibrary is not persisted on external_skills.
            "agent_skills": None,
            # Module version update aggregation is owned by ModuleManager — not invented here.
            "updates_available": None,
            "classifications": {
                "all": installed + catalog,
                "core": installed,
                "external": catalog,
                "tools": self.count_skills_with_scripts(include_catalog=True),
                "agent": None,
            },
            "truth": {
                "agent_skills_unmeasured": True,
                "updates_available_unmeasured": True,
                "core_means_installed_non_catalog": True,
                "external_means_catalog_only": True,
                "tools_means_nonempty_script_refs": True,
            },
        }

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

    # --- install operations ---

    def create_install_operation(
        self,
        *,
        module_id: str,
        plan_hash: str,
        plan: dict[str, Any] | str,
        status: str = "PENDING",
        phase: str = "PLANNING",
        operation_id: str | None = None,
        requested_ref: str | None = None,
        progress: float | None = None,
        job_id: str | None = None,
        approval_id: str | None = None,
        package_manager: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        retryable: bool = False,
        rollback_status: str | None = None,
        idempotency_key: str | None = None,
        started_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.find_active_install_operation(module_id, idempotency_key)
            if existing is not None:
                return existing

        now = utc_now()
        oid = operation_id or str(uuid.uuid4())
        plan_json = (
            plan
            if isinstance(plan, str)
            else json.dumps(plan or {}, separators=(",", ":"))
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            # Application-level active uniqueness (partial unique index is the DB guard).
            if idempotency_key:
                conflict = conn.execute(
                    """
                    SELECT operation_id FROM external_install_operations
                    WHERE idempotency_key = ?
                      AND status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'COMPLETED', 'READY')
                    LIMIT 1
                    """,
                    (idempotency_key,),
                ).fetchone()
                if conflict:
                    return self.get_install_operation(str(conflict["operation_id"])) or {}
            conn.execute(
                """
                INSERT INTO external_install_operations(
                    operation_id, module_id, requested_ref, status, phase, progress,
                    job_id, approval_id, plan_hash, plan_json, package_manager,
                    error_code, error_detail, retryable, rollback_status,
                    idempotency_key, started_at, updated_at, completed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    oid,
                    module_id,
                    requested_ref,
                    status,
                    phase,
                    progress,
                    job_id,
                    approval_id,
                    plan_hash,
                    plan_json,
                    package_manager,
                    error_code,
                    error_detail,
                    1 if retryable else 0,
                    rollback_status,
                    idempotency_key,
                    started_at or now,
                    now,
                    None,
                    json.dumps(metadata or {}, separators=(",", ":")),
                ),
            )
        return self.get_install_operation(oid) or {}

    def get_install_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM external_install_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            return self._install_operation_row(row) if row else None

    def update_install_operation(
        self,
        operation_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        progress: float | None = None,
        job_id: str | None = None,
        approval_id: str | None = None,
        package_manager: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        retryable: bool | None = None,
        rollback_status: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        clear_error: bool = False,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT * FROM external_install_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is None:
                return None

            new_status = status if status is not None else existing["status"]
            sets: list[str] = ["updated_at = ?"]
            params: list[Any] = [now]

            def _set(col: str, value: Any) -> None:
                sets.append(f"{col} = ?")
                params.append(value)

            if status is not None:
                _set("status", status)
            if phase is not None:
                _set("phase", phase)
            if progress is not None:
                _set("progress", progress)
            if job_id is not None:
                _set("job_id", job_id)
            if approval_id is not None:
                _set("approval_id", approval_id)
            if package_manager is not None:
                _set("package_manager", package_manager)
            if clear_error:
                _set("error_code", None)
                _set("error_detail", None)
            else:
                if error_code is not None:
                    _set("error_code", error_code)
                if error_detail is not None:
                    _set("error_detail", error_detail)
            if retryable is not None:
                _set("retryable", 1 if retryable else 0)
            if rollback_status is not None:
                _set("rollback_status", rollback_status)
            if started_at is not None:
                _set("started_at", started_at)
            if metadata is not None:
                _set("metadata_json", json.dumps(metadata, separators=(",", ":")))

            resolved_completed = completed_at
            if resolved_completed is None and str(new_status) in _TERMINAL_INSTALL_STATUSES:
                if not existing["completed_at"]:
                    resolved_completed = now
            if resolved_completed is not None:
                _set("completed_at", resolved_completed)

            params.append(operation_id)
            conn.execute(
                f"UPDATE external_install_operations SET {', '.join(sets)} WHERE operation_id = ?",
                params,
            )
        return self.get_install_operation(operation_id)

    def find_active_install_operation(
        self,
        module_id: str,
        idempotency_key: str | None,
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM external_install_operations
                WHERE module_id = ?
                  AND idempotency_key = ?
                  AND status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'COMPLETED', 'READY')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (module_id, idempotency_key),
            ).fetchone()
            return self._install_operation_row(row) if row else None

    def list_install_operations(self, module_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM external_install_operations
                WHERE module_id = ?
                ORDER BY updated_at DESC
                """,
                (module_id,),
            ).fetchall()
            return [self._install_operation_row(r) for r in rows]

    def add_dependency_receipt(
        self,
        *,
        operation_id: str,
        dependency_id: str,
        status: str,
        receipt_id: str | None = None,
        state_before: str | None = None,
        state_after: str | None = None,
        package_manager: str | None = None,
        packages: list[str] | tuple[str, ...] | None = None,
        observed_version_before: str | None = None,
        observed_version_after: str | None = None,
        newly_installed: bool = False,
        command_fingerprint: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        rid = receipt_id or str(uuid.uuid4())
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO external_install_dependency_receipts(
                    receipt_id, operation_id, dependency_id, state_before, state_after,
                    package_manager, packages_json, observed_version_before,
                    observed_version_after, newly_installed, command_fingerprint,
                    started_at, completed_at, status, error_code, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    operation_id,
                    dependency_id,
                    state_before,
                    state_after,
                    package_manager,
                    json.dumps(list(packages or []), separators=(",", ":")),
                    observed_version_before,
                    observed_version_after,
                    1 if newly_installed else 0,
                    command_fingerprint,
                    started_at or now,
                    completed_at,
                    status,
                    error_code,
                    json.dumps(metadata or {}, separators=(",", ":")),
                ),
            )
        receipts = self.list_dependency_receipts(operation_id)
        for item in receipts:
            if item.get("receipt_id") == rid:
                return item
        return {"receipt_id": rid, "operation_id": operation_id, "dependency_id": dependency_id}

    def list_dependency_receipts(self, operation_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM external_install_dependency_receipts
                WHERE operation_id = ?
                ORDER BY started_at ASC, receipt_id ASC
                """,
                (operation_id,),
            ).fetchall()
            return [self._dependency_receipt_row(r) for r in rows]

    def _install_operation_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "module_id": row["module_id"],
            "requested_ref": row["requested_ref"],
            "status": row["status"],
            "phase": row["phase"],
            "progress": row["progress"],
            "job_id": row["job_id"],
            "approval_id": row["approval_id"],
            "plan_hash": row["plan_hash"],
            "plan": json.loads(row["plan_json"] or "{}"),
            "package_manager": row["package_manager"],
            "error_code": row["error_code"],
            "error_detail": row["error_detail"],
            "retryable": bool(row["retryable"]),
            "rollback_status": row["rollback_status"],
            "idempotency_key": row["idempotency_key"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    def _dependency_receipt_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "receipt_id": row["receipt_id"],
            "operation_id": row["operation_id"],
            "dependency_id": row["dependency_id"],
            "state_before": row["state_before"],
            "state_after": row["state_after"],
            "package_manager": row["package_manager"],
            "packages": json.loads(row["packages_json"] or "[]"),
            "observed_version_before": row["observed_version_before"],
            "observed_version_after": row["observed_version_after"],
            "newly_installed": bool(row["newly_installed"]),
            "command_fingerprint": row["command_fingerprint"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "error_code": row["error_code"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }
