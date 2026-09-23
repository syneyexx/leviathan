"""First-class Projects / Workspaces (U381) — scope without duplicating domain storage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    project_id: str
    name: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "truth": {
                "workspace_scopes_not_duplicates_domain_storage": True,
            },
        }


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    name: str
    created_at: str
    updated_at: str
    default_workspace_id: str | None = None
    status: str = "ACTIVE"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "default_workspace_id": self.default_workspace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "truth": {
                "project_is_scope_not_second_database": True,
                "domains_keep_own_storage": True,
            },
        }


@dataclass(frozen=True)
class ProjectBinding:
    """Links a domain entity into a project without moving its bytes."""

    binding_id: str
    project_id: str
    workspace_id: str | None
    domain: str  # chat | research | coding | browser | artifact | job | run | memory
    entity_id: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "domain": self.domain,
            "entity_id": self.entity_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class ProjectStore:
    """Durable project/workspace registry in the canonical control-plane DB."""

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

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS product_projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    default_workspace_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS product_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS product_project_bindings (
                    binding_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    workspace_id TEXT,
                    domain TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, domain, entity_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_bindings_project "
                "ON product_project_bindings(project_id, domain, created_at)"
            )

    def create_project(
        self,
        name: str,
        *,
        project_id: str | None = None,
        workspace_name: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ProjectRecord, WorkspaceRecord]:
        now = utc_now()
        pid = project_id or f"proj_{uuid.uuid4().hex[:12]}"
        wid = f"ws_{uuid.uuid4().hex[:12]}"
        project = ProjectRecord(
            project_id=pid,
            name=name,
            created_at=now,
            updated_at=now,
            default_workspace_id=wid,
            metadata=dict(metadata or {}),
        )
        workspace = WorkspaceRecord(
            workspace_id=wid,
            project_id=pid,
            name=workspace_name,
            created_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO product_projects(
                    project_id, name, status, default_workspace_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.project_id,
                    project.name,
                    project.status,
                    project.default_workspace_id,
                    json.dumps(project.metadata),
                    project.created_at,
                    project.updated_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO product_workspaces(workspace_id, project_id, name, metadata_json, created_at)
                VALUES (?, ?, ?, '{}', ?)
                """,
                (workspace.workspace_id, workspace.project_id, workspace.name, workspace.created_at),
            )
        return project, workspace

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM product_projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            return None
        return ProjectRecord(
            project_id=row["project_id"],
            name=row["name"],
            status=row["status"],
            default_workspace_id=row["default_workspace_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def list_projects(self, *, limit: int = 100) -> list[ProjectRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM product_projects ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [
            ProjectRecord(
                project_id=row["project_id"],
                name=row["name"],
                status=row["status"],
                default_workspace_id=row["default_workspace_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def list_workspaces(self, project_id: str) -> list[WorkspaceRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM product_workspaces WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        return [
            WorkspaceRecord(
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                name=row["name"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def bind(
        self,
        *,
        project_id: str,
        domain: str,
        entity_id: str,
        workspace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectBinding:
        if self.get_project(project_id) is None:
            raise KeyError(f"Unknown project: {project_id}")
        binding = ProjectBinding(
            binding_id=f"bind_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            workspace_id=workspace_id,
            domain=domain,
            entity_id=entity_id,
            created_at=utc_now(),
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO product_project_bindings(
                    binding_id, project_id, workspace_id, domain, entity_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, domain, entity_id) DO UPDATE SET
                    workspace_id=excluded.workspace_id,
                    metadata_json=excluded.metadata_json
                """,
                (
                    binding.binding_id,
                    binding.project_id,
                    binding.workspace_id,
                    binding.domain,
                    binding.entity_id,
                    json.dumps(binding.metadata),
                    binding.created_at,
                ),
            )
        return binding

    def list_bindings(
        self,
        project_id: str,
        *,
        domain: str | None = None,
        limit: int = 200,
    ) -> list[ProjectBinding]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        params.append(max(1, min(limit, 1000)))
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM product_project_bindings
                WHERE {where}
                ORDER BY created_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            ProjectBinding(
                binding_id=row["binding_id"],
                project_id=row["project_id"],
                workspace_id=row["workspace_id"],
                domain=row["domain"],
                entity_id=row["entity_id"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]
