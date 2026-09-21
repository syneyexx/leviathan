"""Durable project continuity — goals, decisions, constraints, assumptions.

Conversation working_state remains a compact per-chat snapshot. This module
owns first-class project state that survives restart and is shared only across
conversations/tasks that explicitly belong to the same project.

Provenance kinds (mutually exclusive labels):
- user_explicit — user stated it
- observed — established from code/sources
- inferred — HADES derived it
- proposal — suggestion only; not active policy
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from database import new_id, utc_now

ProvenanceKind = Literal["user_explicit", "observed", "inferred", "proposal"]
ItemKind = Literal[
    "goal",
    "acceptance_criterion",
    "constraint",
    "preference",
    "decision",
    "assumption",
    "open_question",
    "blocker",
    "dependency",
    "task_ref",
    "artifact_ref",
]

PROVENANCE_KINDS = frozenset({"user_explicit", "observed", "inferred", "proposal"})
ITEM_KINDS = frozenset(
    {
        "goal",
        "acceptance_criterion",
        "constraint",
        "preference",
        "decision",
        "assumption",
        "open_question",
        "blocker",
        "dependency",
        "task_ref",
        "artifact_ref",
    }
)
ACTIVE_STATUSES = frozenset({"active", "open", "unverified"})
ASSUMPTION_STATUSES = frozenset({"unverified", "verified", "falsified", "superseded", "excluded"})


class ProjectContinuityService:
    """SQLite-backed project continuity store (core DB, not a second database)."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        # Reuse Database.connection() so WAL / busy_timeout / migrations stay consistent.
        return self.db.connection()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_items (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    provenance TEXT NOT NULL DEFAULT 'inferred',
                    status TEXT NOT NULL DEFAULT 'active',
                    scope TEXT NOT NULL DEFAULT 'project',
                    source_message_id TEXT,
                    source_conversation_id TEXT,
                    source_version TEXT,
                    supersedes_id TEXT,
                    superseded_by TEXT,
                    excluded INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_project_items_project_kind
                    ON project_items(project_id, kind, status);

                CREATE TABLE IF NOT EXISTS project_relations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    related_project_id TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'related',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, related_project_id, relation)
                );

                CREATE TABLE IF NOT EXISTS project_item_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_project(
        self,
        name: str,
        *,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        item = {
            "id": new_id("proj"),
            "name": (name or "Project").strip()[:200] or "Project",
            "description": (description or "").strip()[:4000],
            "status": "active",
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO projects(id, name, description, status, metadata_json, created_at, updated_at)
                   VALUES (:id, :name, :description, :status, :metadata_json, :created_at, :updated_at)""",
                item,
            )
        return self.get_project(item["id"]) or item

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return None
        return self._project_row(row)

    def list_projects(self, *, status: str | None = "active", limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM projects"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._project_row(r) for r in rows]

    def update_project(self, project_id: str, **fields: Any) -> dict[str, Any]:
        current = self.get_project(project_id)
        if not current:
            raise KeyError(project_id)
        allowed = {"name", "description", "status", "metadata"}
        values: dict[str, Any] = {"updated_at": utc_now()}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "metadata":
                values["metadata_json"] = json.dumps(value or {}, ensure_ascii=False)
            else:
                values[key] = value
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                [*values.values(), project_id],
            )
        return self.get_project(project_id) or current

    def add_item(
        self,
        project_id: str,
        *,
        kind: str,
        title: str,
        body: str = "",
        provenance: str = "inferred",
        status: str = "active",
        scope: str = "project",
        source_message_id: str | None = None,
        source_conversation_id: str | None = None,
        source_version: str | None = None,
        supersedes_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        replace_overlapping: bool = True,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        kind = str(kind or "").strip()
        if kind not in ITEM_KINDS:
            raise ValueError(f"Unknown project item kind: {kind}")
        provenance = str(provenance or "inferred").strip()
        if provenance not in PROVENANCE_KINDS:
            raise ValueError(f"Unknown provenance: {provenance}")
        now = utc_now()
        item = {
            "id": new_id("pitem"),
            "project_id": project_id,
            "kind": kind,
            "title": (title or "").strip()[:500] or kind,
            "body": (body or "").strip()[:8000],
            "provenance": provenance,
            "status": (status or "active").strip()[:40],
            "scope": (scope or "project").strip()[:40],
            "source_message_id": source_message_id,
            "source_conversation_id": source_conversation_id,
            "source_version": source_version,
            "supersedes_id": supersedes_id,
            "superseded_by": None,
            "excluded": 0,
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }

        superseded: list[str] = []
        with self._connect() as conn:
            if replace_overlapping and provenance == "user_explicit" and kind in {
                "constraint",
                "preference",
                "decision",
                "goal",
                "acceptance_criterion",
            }:
                superseded = self._supersede_overlapping(conn, project_id, item)
            if supersedes_id and supersedes_id not in superseded:
                self._mark_superseded(conn, supersedes_id, item["id"])
                superseded.append(supersedes_id)
            conn.execute(
                """INSERT INTO project_items(
                    id, project_id, kind, title, body, provenance, status, scope,
                    source_message_id, source_conversation_id, source_version,
                    supersedes_id, superseded_by, excluded, metadata_json, created_at, updated_at
                ) VALUES (
                    :id, :project_id, :kind, :title, :body, :provenance, :status, :scope,
                    :source_message_id, :source_conversation_id, :source_version,
                    :supersedes_id, :superseded_by, :excluded, :metadata_json, :created_at, :updated_at
                )""",
                item,
            )
            conn.execute(
                "UPDATE projects SET updated_at=? WHERE id=?",
                (now, project_id),
            )
            self._history(
                conn,
                item_id=item["id"],
                project_id=project_id,
                event="created",
                before=None,
                after=item,
            )
            for old_id in superseded:
                self._history(
                    conn,
                    item_id=old_id,
                    project_id=project_id,
                    event="superseded",
                    before={"id": old_id},
                    after={"superseded_by": item["id"]},
                )
        result = self.get_item(item["id"]) or item
        result["superseded_ids"] = superseded
        return result

    def _supersede_overlapping(self, conn: sqlite3.Connection, project_id: str, new_item: dict[str, Any]) -> list[str]:
        rows = conn.execute(
            """SELECT * FROM project_items
               WHERE project_id=? AND kind=? AND COALESCE(excluded,0)=0
                 AND status NOT IN ('superseded','excluded','falsified')
                 AND superseded_by IS NULL""",
            (project_id, new_item["kind"]),
        ).fetchall()
        new_tokens = _tokens(f"{new_item['title']} {new_item['body']}")
        out: list[str] = []
        for row in rows:
            old = dict(row)
            old_tokens = _tokens(f"{old.get('title') or ''} {old.get('body') or ''}")
            shared = new_tokens & old_tokens
            # Explicit user constraint/decision replaces overlapping prior of same kind.
            if len(shared) >= 2 or (new_item["kind"] == "constraint" and old.get("provenance") != "user_explicit" and len(shared) >= 1):
                self._mark_superseded(conn, old["id"], new_item["id"])
                out.append(old["id"])
        return out

    def _mark_superseded(self, conn: sqlite3.Connection, old_id: str, new_id: str) -> None:
        conn.execute(
            """UPDATE project_items
               SET status='superseded', superseded_by=?, updated_at=?
               WHERE id=? AND superseded_by IS NULL""",
            (new_id, utc_now(), old_id),
        )

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_items WHERE id=?", (item_id,)).fetchone()
        return self._item_row(row) if row else None

    def list_items(
        self,
        project_id: str,
        *,
        kind: str | None = None,
        include_excluded: bool = False,
        include_superseded: bool = False,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM project_items WHERE project_id=?"
        params: list[Any] = [project_id]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if not include_excluded:
            sql += " AND COALESCE(excluded,0)=0"
        if active_only and not include_superseded:
            sql += " AND status NOT IN ('superseded','excluded','falsified')"
            sql += " AND superseded_by IS NULL"
        sql += " ORDER BY created_at, rowid"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._item_row(r) for r in rows]

    def correct_item(
        self,
        item_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        provenance: str = "user_explicit",
        source_message_id: str | None = None,
    ) -> dict[str, Any]:
        """User correction creates a superseding item and preserves history."""
        current = self.get_item(item_id)
        if not current:
            raise KeyError(item_id)
        return self.add_item(
            current["project_id"],
            kind=current["kind"],
            title=title if title is not None else current["title"],
            body=body if body is not None else current["body"],
            provenance=provenance,
            status=status or "active",
            scope=current.get("scope") or "project",
            source_message_id=source_message_id,
            source_conversation_id=current.get("source_conversation_id"),
            supersedes_id=item_id,
            metadata={"corrected_from": item_id},
            replace_overlapping=False,
        )

    def exclude_item(self, item_id: str, *, reason: str = "user_excluded") -> dict[str, Any]:
        current = self.get_item(item_id)
        if not current:
            raise KeyError(item_id)
        meta = dict(current.get("metadata") or {})
        meta["exclude_reason"] = reason
        with self._connect() as conn:
            conn.execute(
                """UPDATE project_items
                   SET excluded=1, status='excluded', metadata_json=?, updated_at=?
                   WHERE id=?""",
                (json.dumps(meta, ensure_ascii=False), utc_now(), item_id),
            )
            self._history(
                conn,
                item_id=item_id,
                project_id=current["project_id"],
                event="excluded",
                before=current,
                after={"excluded": True, "reason": reason},
            )
        return self.get_item(item_id) or current

    def set_assumption_status(self, item_id: str, status: str) -> dict[str, Any]:
        if status not in ASSUMPTION_STATUSES:
            raise ValueError(f"Invalid assumption status: {status}")
        current = self.get_item(item_id)
        if not current:
            raise KeyError(item_id)
        if current.get("kind") != "assumption":
            raise ValueError("Item is not an assumption")
        with self._connect() as conn:
            conn.execute(
                "UPDATE project_items SET status=?, updated_at=? WHERE id=?",
                (status, utc_now(), item_id),
            )
            self._history(
                conn,
                item_id=item_id,
                project_id=current["project_id"],
                event="assumption_status",
                before={"status": current.get("status")},
                after={"status": status},
            )
        return self.get_item(item_id) or current

    def link_conversation(self, project_id: str, conversation_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        with self._connect() as conn:
            # conversations.project_id already exists on core schema
            conn.execute(
                "UPDATE conversations SET project_id=?, updated_at=? WHERE id=?",
                (project_id, utc_now(), conversation_id),
            )
        return {"project_id": project_id, "conversation_id": conversation_id}

    def relate_projects(self, project_id: str, related_project_id: str, *, relation: str = "related") -> dict[str, Any]:
        if project_id == related_project_id:
            raise ValueError("Cannot relate a project to itself")
        if not self.get_project(project_id) or not self.get_project(related_project_id):
            raise KeyError("project not found")
        item = {
            "id": new_id("prel"),
            "project_id": project_id,
            "related_project_id": related_project_id,
            "relation": (relation or "related").strip()[:40],
            "created_at": utc_now(),
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO project_relations(id, project_id, related_project_id, relation, created_at)
                   VALUES (:id, :project_id, :related_project_id, :relation, :created_at)""",
                item,
            )
        return item

    def related_project_ids(self, project_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT related_project_id FROM project_relations WHERE project_id=?
                   UNION
                   SELECT project_id FROM project_relations WHERE related_project_id=?""",
                (project_id, project_id),
            ).fetchall()
        return {str(r[0]) for r in rows}

    def context_package(
        self,
        project_id: str,
        *,
        include_proposals: bool = False,
        max_items: int = 40,
    ) -> dict[str, Any]:
        """Compact, attributable package for resume after restart."""
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        items = self.list_items(project_id, active_only=True)
        stale_assumptions = [
            item
            for item in self.list_items(
                project_id,
                kind="assumption",
                active_only=False,
                include_superseded=True,
            )
            if item.get("status") in {"falsified", "superseded"}
        ]
        if not include_proposals:
            items = [i for i in items if i.get("provenance") != "proposal"]
            stale_assumptions = [i for i in stale_assumptions if i.get("provenance") != "proposal"]
        # Stale assumptions are reported separately and never re-enter active context.
        active: list[dict[str, Any]] = []
        for item in items:
            if item.get("kind") == "assumption" and item.get("status") == "unverified":
                # Keep but flag — caller must see verification status.
                active.append(item)
                continue
            active.append(item)
        active = active[: max(1, min(int(max_items), 200))]
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for item in active:
            by_kind.setdefault(str(item["kind"]), []).append(_public_item(item))
        return {
            "project": {
                "id": project["id"],
                "name": project["name"],
                "description": project["description"],
                "status": project["status"],
                "updated_at": project["updated_at"],
            },
            "goals": by_kind.get("goal", []),
            "acceptance_criteria": by_kind.get("acceptance_criterion", []),
            "constraints": by_kind.get("constraint", []),
            "preferences": by_kind.get("preference", []),
            "decisions": by_kind.get("decision", []),
            "assumptions": by_kind.get("assumption", []),
            "open_questions": by_kind.get("open_question", []),
            "blockers": by_kind.get("blocker", []),
            "dependencies": by_kind.get("dependency", []),
            "task_refs": by_kind.get("task_ref", []),
            "artifact_refs": by_kind.get("artifact_ref", []),
            "stale_assumptions": [_public_item(i) for i in stale_assumptions],
            "related_project_ids": sorted(self.related_project_ids(project_id)),
            "provenance_legend": {
                "user_explicit": "User stated",
                "observed": "Established from code/sources",
                "inferred": "HADES derived",
                "proposal": "Suggestion only",
            },
            "package_version": "project_continuity_v1",
            "generated_at": utc_now(),
        }

    def ingest_working_state(
        self,
        project_id: str,
        working_state: dict[str, Any] | None,
        *,
        conversation_id: str | None = None,
        default_provenance: str = "inferred",
    ) -> dict[str, Any]:
        """Lift conversation working_state into durable project items (non-destructive)."""
        state = dict(working_state or {})
        created: list[str] = []
        mapping = [
            ("constraints", "constraint", "user_explicit"),
            ("decisions", "decision", "user_explicit"),
            ("proposals", "proposal", "proposal"),
            ("open_questions", "open_question", "inferred"),
        ]
        for key, kind, provenance in mapping:
            for raw in state.get(key) or []:
                text = str(raw).strip()
                if not text:
                    continue
                item = self.add_item(
                    project_id,
                    kind=kind,
                    title=text[:200],
                    body=text,
                    provenance=provenance if provenance in PROVENANCE_KINDS else default_provenance,
                    source_conversation_id=conversation_id,
                    replace_overlapping=provenance == "user_explicit",
                )
                created.append(item["id"])
        goal = str(state.get("goal") or "").strip()
        if goal:
            item = self.add_item(
                project_id,
                kind="goal",
                title=goal[:200],
                body=goal,
                provenance="user_explicit",
                source_conversation_id=conversation_id,
            )
            created.append(item["id"])
        return {"created_ids": created, "count": len(created)}

    def item_history(self, item_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM project_item_history WHERE item_id=?
                   ORDER BY id DESC LIMIT ?""",
                (item_id, max(1, min(int(limit), 200))),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field in ("before_json", "after_json"):
                raw = item.pop(field, None)
                key = "before" if field.startswith("before") else "after"
                try:
                    item[key] = json.loads(raw) if raw else None
                except Exception:
                    item[key] = None
            out.append(item)
        return out

    def _history(
        self,
        conn: sqlite3.Connection,
        *,
        item_id: str,
        project_id: str,
        event: str,
        before: Any,
        after: Any,
    ) -> None:
        conn.execute(
            """INSERT INTO project_item_history(item_id, project_id, event, before_json, after_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                project_id,
                event,
                json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
                json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
                utc_now(),
            ),
        )

    @staticmethod
    def _project_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
        except Exception:
            item["metadata"] = {}
        return item

    @staticmethod
    def _item_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["excluded"] = bool(item.get("excluded"))
        try:
            item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
        except Exception:
            item["metadata"] = {}
        return item


def _tokens(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-zA-Z0-9]{4,}", (text or "").lower()))


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "title": item.get("title"),
        "body": item.get("body"),
        "provenance": item.get("provenance"),
        "status": item.get("status"),
        "scope": item.get("scope"),
        "source_message_id": item.get("source_message_id"),
        "source_conversation_id": item.get("source_conversation_id"),
        "source_version": item.get("source_version"),
        "supersedes_id": item.get("supersedes_id"),
        "updated_at": item.get("updated_at"),
    }


def apply_project_context_to_prompt(package: dict[str, Any] | None) -> str:
    """Render a compact, attributable context block for model prompts (no CoT)."""
    if not package:
        return ""
    lines = [f"Project: {package.get('project', {}).get('name') or package.get('project', {}).get('id')}"]
    for label, key in (
        ("Goals", "goals"),
        ("Acceptance", "acceptance_criteria"),
        ("Constraints", "constraints"),
        ("Decisions", "decisions"),
        ("Open questions", "open_questions"),
        ("Blockers", "blockers"),
    ):
        items = package.get(key) or []
        if not items:
            continue
        lines.append(f"{label}:")
        for item in items[:8]:
            prov = item.get("provenance") or "inferred"
            lines.append(f"- [{prov}] {item.get('title') or item.get('body')}")
    stale = package.get("stale_assumptions") or []
    if stale:
        lines.append("Stale assumptions (do not treat as active):")
        for item in stale[:5]:
            lines.append(f"- {item.get('title')} ({item.get('status')})")
    return "\n".join(lines)
