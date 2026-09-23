"""Unified work timeline across chat/research/coding/browser/artifacts (U382).

Projection over project bindings + appended timeline events — not a second event bus.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from Data.modules.projects.store import ProjectStore


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    project_id: str
    domain: str
    name: str
    created_at_ms: float
    entity_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    workspace_id: str | None = None
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "domain": self.domain,
            "name": self.name,
            "entity_id": self.entity_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "summary": self.summary,
            "created_at_ms": self.created_at_ms,
            "metadata": self.metadata,
            "truth": {
                "timeline_is_projection_not_second_bus": True,
                "domains_remain_owners": True,
            },
        }


class WorkTimeline:
    """Append-only project timeline + bind-aware listing."""

    def __init__(self, db_path: Path, *, projects: ProjectStore | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.projects = projects

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_timeline_events (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    workspace_id TEXT,
                    domain TEXT NOT NULL,
                    name TEXT NOT NULL,
                    entity_id TEXT,
                    run_id TEXT,
                    trace_id TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ms REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_timeline_project "
                "ON work_timeline_events(project_id, created_at_ms)"
            )

    def append(
        self,
        *,
        project_id: str,
        domain: str,
        name: str,
        entity_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        workspace_id: str | None = None,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        created_at_ms: float | None = None,
        bind: bool = True,
    ) -> TimelineEvent:
        event = TimelineEvent(
            event_id=f"tl_{uuid.uuid4().hex[:14]}",
            project_id=project_id,
            domain=domain,
            name=name,
            created_at_ms=created_at_ms if created_at_ms is not None else time.time() * 1000,
            entity_id=entity_id,
            run_id=run_id,
            trace_id=trace_id,
            workspace_id=workspace_id,
            summary=summary,
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO work_timeline_events(
                    event_id, project_id, workspace_id, domain, name, entity_id,
                    run_id, trace_id, summary, metadata_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.workspace_id,
                    event.domain,
                    event.name,
                    event.entity_id,
                    event.run_id,
                    event.trace_id,
                    event.summary,
                    json.dumps(event.metadata),
                    event.created_at_ms,
                ),
            )
        if bind and self.projects is not None and entity_id:
            self.projects.bind(
                project_id=project_id,
                domain=domain,
                entity_id=entity_id,
                workspace_id=workspace_id,
                metadata={"timeline_event_id": event.event_id},
            )
        return event

    def list_for_project(
        self,
        project_id: str,
        *,
        domains: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[TimelineEvent]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if domains:
            placeholders = ",".join("?" for _ in domains)
            clauses.append(f"domain IN ({placeholders})")
            params.extend(domains)
        params.append(max(1, min(limit, 2000)))
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM work_timeline_events
                WHERE {where}
                ORDER BY created_at_ms ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            TimelineEvent(
                event_id=row["event_id"],
                project_id=row["project_id"],
                workspace_id=row["workspace_id"],
                domain=row["domain"],
                name=row["name"],
                entity_id=row["entity_id"],
                run_id=row["run_id"],
                trace_id=row["trace_id"],
                summary=row["summary"] or "",
                created_at_ms=float(row["created_at_ms"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def domains_present(self, project_id: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT domain FROM work_timeline_events
                WHERE project_id = ?
                ORDER BY domain ASC
                """,
                (project_id,),
            ).fetchall()
        return [row["domain"] for row in rows]
