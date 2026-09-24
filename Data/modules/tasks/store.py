"""SQLite persistence for the Tasks planning domain."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    AssigneeType,
    BoardColumn,
    ExecutionBinding,
    SourceType,
    TaskDependency,
    TaskError,
    TaskEvent,
    TaskNote,
    TaskPriority,
    TaskRecord,
    TaskSubtask,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskStore:
    """Durable task planning records in the shared LEVIATHAN SQLite DB."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                board_column TEXT NOT NULL,
                blocked INTEGER NOT NULL DEFAULT 0,
                blocked_reason TEXT,
                blocked_reason_code TEXT,
                priority TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                project TEXT,
                assignee_type TEXT NOT NULL DEFAULT 'none',
                assignee_id TEXT,
                assignee_name TEXT,
                due_at TEXT,
                planned_start_at TEXT,
                completed_at TEXT,
                progress REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT,
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_ref TEXT,
                execution_binding TEXT NOT NULL DEFAULT 'manual',
                job_id TEXT,
                workflow_id TEXT,
                mission_id TEXT,
                run_id TEXT,
                approval_id TEXT,
                schedule_id TEXT,
                capability_id TEXT,
                capability_arguments_json TEXT NOT NULL DEFAULT '{}',
                mission_request TEXT,
                execution_state TEXT,
                execution_error TEXT,
                execution_phase TEXT,
                execution_attempt INTEGER,
                execution_progress REAL,
                execution_started_at TEXT,
                execution_finished_at TEXT,
                board_order INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL DEFAULT 'operator',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_subtasks (
                subtask_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_notes (
                note_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                body TEXT NOT NULL,
                author_type TEXT NOT NULL DEFAULT 'operator',
                author_id TEXT,
                author_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_dependencies (
                dependency_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                depends_on_task_id TEXT NOT NULL,
                soft INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(task_id, depends_on_task_id),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_events (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL DEFAULT 'system',
                actor_id TEXT,
                source_type TEXT,
                source_ref TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
            """
        )
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_tasks_board ON tasks(board_column)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_archived ON tasks(archived_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_job ON tasks(job_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_workflow ON tasks(workflow_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_mission ON tasks(mission_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source_type, source_ref)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_source_unique "
            "ON tasks(source_type, source_ref) WHERE source_ref IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_task_subtasks_task ON task_subtasks(task_id, sort_order)",
            "CREATE INDEX IF NOT EXISTS idx_task_notes_task ON task_notes(task_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id)",
            "CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id)",
            "CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_task_events_created ON task_events(created_at)",
        ):
            conn.execute(ddl)

    # ── Tasks CRUD ──────────────────────────────────────────────────────────

    def create_task(self, record: TaskRecord, *, conn: sqlite3.Connection | None = None) -> TaskRecord:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO tasks(
                    task_id, title, description, board_column, blocked, blocked_reason,
                    blocked_reason_code, priority, tags_json, project, assignee_type,
                    assignee_id, assignee_name, due_at, planned_start_at, completed_at,
                    progress, created_at, updated_at, archived_at, source_type, source_ref,
                    execution_binding, job_id, workflow_id, mission_id, run_id, approval_id,
                    schedule_id, capability_id, capability_arguments_json, mission_request,
                    execution_state, execution_error, execution_phase, execution_attempt,
                    execution_progress, execution_started_at, execution_finished_at,
                    board_order, created_by, metadata_json
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                self._task_row_values(record),
            )

        if conn is not None:
            _write(conn)
            return record
        with self.connect() as c:
            self._ensure_schema(c)
            _write(c)
        return record

    def get_task(self, task_id: str, *, include_archived: bool = True) -> TaskRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        record = self._task_from_row(row)
        if not include_archived and record.archived_at:
            return None
        return record

    def get_by_source(self, source_type: str, source_ref: str) -> TaskRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM tasks WHERE source_type = ? AND source_ref = ?",
                (source_type, source_ref),
            ).fetchone()
        return self._task_from_row(row) if row else None

    def update_task(self, record: TaskRecord, *, conn: sqlite3.Connection | None = None) -> TaskRecord:
        record.updated_at = utc_now()

        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                UPDATE tasks SET
                    title=?, description=?, board_column=?, blocked=?, blocked_reason=?,
                    blocked_reason_code=?, priority=?, tags_json=?, project=?, assignee_type=?,
                    assignee_id=?, assignee_name=?, due_at=?, planned_start_at=?, completed_at=?,
                    progress=?, updated_at=?, archived_at=?, source_type=?, source_ref=?,
                    execution_binding=?, job_id=?, workflow_id=?, mission_id=?, run_id=?,
                    approval_id=?, schedule_id=?, capability_id=?, capability_arguments_json=?,
                    mission_request=?, execution_state=?, execution_error=?, execution_phase=?,
                    execution_attempt=?, execution_progress=?, execution_started_at=?,
                    execution_finished_at=?, board_order=?, created_by=?, metadata_json=?
                WHERE task_id=?
                """,
                (
                    record.title,
                    record.description,
                    record.board_column.value,
                    1 if record.blocked else 0,
                    record.blocked_reason,
                    record.blocked_reason_code,
                    record.priority.value,
                    json.dumps(list(record.tags)),
                    record.project,
                    record.assignee_type.value,
                    record.assignee_id,
                    record.assignee_name,
                    record.due_at,
                    record.planned_start_at,
                    record.completed_at,
                    record.progress,
                    record.updated_at,
                    record.archived_at,
                    record.source_type.value,
                    record.source_ref,
                    record.execution_binding.value,
                    record.job_id,
                    record.workflow_id,
                    record.mission_id,
                    record.run_id,
                    record.approval_id,
                    record.schedule_id,
                    record.capability_id,
                    json.dumps(dict(record.capability_arguments)),
                    record.mission_request,
                    record.execution_state,
                    record.execution_error,
                    record.execution_phase,
                    record.execution_attempt,
                    record.execution_progress,
                    record.execution_started_at,
                    record.execution_finished_at,
                    record.board_order,
                    record.created_by,
                    json.dumps(dict(record.metadata)),
                    record.task_id,
                ),
            )

        if conn is not None:
            _write(conn)
            return record
        with self.connect() as c:
            self._ensure_schema(c)
            _write(c)
        return record

    def list_tasks(
        self,
        *,
        search: str | None = None,
        board_column: str | None = None,
        execution_state: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        blocked: bool | None = None,
        overdue: bool | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        project: str | None = None,
        archived: bool = False,
        limit: int = 200,
        offset: int = 0,
        now_iso: str | None = None,
    ) -> list[TaskRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if archived:
            clauses.append("archived_at IS NOT NULL")
        else:
            clauses.append("archived_at IS NULL")
        if board_column:
            clauses.append("board_column = ?")
            params.append(board_column)
        if execution_state:
            clauses.append("execution_state = ?")
            params.append(execution_state)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if assignee:
            if assignee == "__none__":
                clauses.append("(assignee_id IS NULL OR assignee_type = 'none')")
            else:
                clauses.append("(assignee_id = ? OR lower(assignee_name) = lower(?))")
                params.extend([assignee, assignee])
        if blocked is not None:
            clauses.append("blocked = ?")
            params.append(1 if blocked else 0)
        if project:
            clauses.append("lower(project) = lower(?)")
            params.append(project)
        if due_from:
            clauses.append("due_at IS NOT NULL AND due_at >= ?")
            params.append(due_from)
        if due_to:
            clauses.append("due_at IS NOT NULL AND due_at <= ?")
            params.append(due_to)
        if overdue is True:
            now = now_iso or utc_now()
            clauses.append(
                "due_at IS NOT NULL AND due_at < ? AND completed_at IS NULL AND board_column != 'done'"
            )
            params.append(now)
        if search:
            like = f"%{search.strip().lower()}%"
            clauses.append(
                "("
                "lower(title) LIKE ? OR lower(description) LIKE ? OR lower(tags_json) LIKE ? "
                "OR lower(COALESCE(project,'')) LIKE ? OR lower(COALESCE(assignee_name,'')) LIKE ? "
                "OR lower(task_id) LIKE ?"
                ")"
            )
            params.extend([like, like, like, like, like, like])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        params.extend([limit, offset])
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"""
                SELECT * FROM tasks {where}
                ORDER BY board_order ASC, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._task_from_row(r) for r in rows]

    def list_all_active(self, *, limit: int = 5000) -> list[TaskRecord]:
        return self.list_tasks(archived=False, limit=limit)

    def next_board_order(self, board_column: str) -> int:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COALESCE(MAX(board_order), 0) + 1 AS n FROM tasks "
                "WHERE board_column = ? AND archived_at IS NULL",
                (board_column,),
            ).fetchone()
        return int(row["n"] if row else 1)

    # ── Events ──────────────────────────────────────────────────────────────

    def append_event(
        self,
        *,
        task_id: str,
        event_type: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        source_type: str | None = None,
        source_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            event_id=str(uuid.uuid4()),
            task_id=task_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            source_type=source_type,
            source_ref=source_ref,
            payload=payload or {},
            created_at=utc_now(),
        )

        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO task_events(
                    event_id, task_id, event_type, actor_type, actor_id,
                    source_type, source_ref, payload_json, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.event_type,
                    event.actor_type,
                    event.actor_id,
                    event.source_type,
                    event.source_ref,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )

        if conn is not None:
            _write(conn)
            return event
        with self.connect() as c:
            self._ensure_schema(c)
            _write(c)
        return event

    def list_events(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        since: str | None = None,
    ) -> list[TaskEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if since:
            clauses.append("created_at > ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        params.extend([limit, offset])
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"""
                SELECT * FROM task_events {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._event_from_row(r) for r in rows]

    # ── Subtasks ────────────────────────────────────────────────────────────

    def create_subtask(self, subtask: TaskSubtask, *, conn: sqlite3.Connection | None = None) -> TaskSubtask:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO task_subtasks(
                    subtask_id, task_id, title, completed, completed_at,
                    sort_order, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    subtask.subtask_id,
                    subtask.task_id,
                    subtask.title,
                    1 if subtask.completed else 0,
                    subtask.completed_at,
                    subtask.sort_order,
                    subtask.created_at,
                    subtask.updated_at,
                ),
            )

        if conn is not None:
            _write(conn)
            return subtask
        with self.connect() as c:
            self._ensure_schema(c)
            _write(c)
        return subtask

    def get_subtask(self, subtask_id: str) -> TaskSubtask | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM task_subtasks WHERE subtask_id = ?", (subtask_id,)
            ).fetchone()
        return self._subtask_from_row(row) if row else None

    def list_subtasks(self, task_id: str) -> list[TaskSubtask]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM task_subtasks WHERE task_id = ? ORDER BY sort_order ASC, created_at ASC",
                (task_id,),
            ).fetchall()
        return [self._subtask_from_row(r) for r in rows]

    def update_subtask(self, subtask: TaskSubtask) -> TaskSubtask:
        subtask.updated_at = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                UPDATE task_subtasks SET title=?, completed=?, completed_at=?,
                    sort_order=?, updated_at=?
                WHERE subtask_id=?
                """,
                (
                    subtask.title,
                    1 if subtask.completed else 0,
                    subtask.completed_at,
                    subtask.sort_order,
                    subtask.updated_at,
                    subtask.subtask_id,
                ),
            )
        return subtask

    def delete_subtask(self, subtask_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute("DELETE FROM task_subtasks WHERE subtask_id = ?", (subtask_id,))
        return cur.rowcount > 0

    # ── Notes ───────────────────────────────────────────────────────────────

    def create_note(self, note: TaskNote, *, conn: sqlite3.Connection | None = None) -> TaskNote:
        def _write(c: sqlite3.Connection) -> None:
            c.execute(
                """
                INSERT INTO task_notes(
                    note_id, task_id, body, author_type, author_id, author_name,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    note.note_id,
                    note.task_id,
                    note.body,
                    note.author_type,
                    note.author_id,
                    note.author_name,
                    note.created_at,
                    note.updated_at,
                ),
            )

        if conn is not None:
            _write(conn)
            return note
        with self.connect() as c:
            self._ensure_schema(c)
            _write(c)
        return note

    def get_note(self, note_id: str) -> TaskNote | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute("SELECT * FROM task_notes WHERE note_id = ?", (note_id,)).fetchone()
        return self._note_from_row(row) if row else None

    def list_notes(self, task_id: str) -> list[TaskNote]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM task_notes WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            ).fetchall()
        return [self._note_from_row(r) for r in rows]

    def update_note(self, note: TaskNote) -> TaskNote:
        note.updated_at = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE task_notes SET body=?, updated_at=? WHERE note_id=?",
                (note.body, note.updated_at, note.note_id),
            )
        return note

    def delete_note(self, note_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute("DELETE FROM task_notes WHERE note_id = ?", (note_id,))
        return cur.rowcount > 0

    # ── Dependencies ────────────────────────────────────────────────────────

    def list_dependencies(self, task_id: str) -> list[TaskDependency]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM task_dependencies WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
        return [self._dep_from_row(r) for r in rows]

    def list_dependents(self, task_id: str) -> list[TaskDependency]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM task_dependencies WHERE depends_on_task_id = ?",
                (task_id,),
            ).fetchall()
        return [self._dep_from_row(r) for r in rows]

    def all_dependency_edges(self) -> list[tuple[str, str]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT task_id, depends_on_task_id FROM task_dependencies"
            ).fetchall()
        return [(str(r["task_id"]), str(r["depends_on_task_id"])) for r in rows]

    def would_create_cycle(self, task_id: str, depends_on_task_id: str) -> bool:
        if task_id == depends_on_task_id:
            return True
        # Walk from depends_on: if we can reach task_id, adding edge task→depends_on cycles
        edges = self.all_dependency_edges()
        graph: dict[str, list[str]] = {}
        for tid, dep in edges:
            graph.setdefault(tid, []).append(dep)
        graph.setdefault(task_id, []).append(depends_on_task_id)
        seen: set[str] = set()
        stack = [depends_on_task_id]
        while stack:
            node = stack.pop()
            if node == task_id:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(graph.get(node, []))
        return False

    def add_dependency(
        self,
        *,
        task_id: str,
        depends_on_task_id: str,
        soft: bool = False,
        conn: sqlite3.Connection | None = None,
    ) -> TaskDependency:
        if task_id == depends_on_task_id:
            raise TaskError("DEPENDENCY_SELF", "A task cannot depend on itself", http_status=422)
        if self.would_create_cycle(task_id, depends_on_task_id):
            raise TaskError(
                "DEPENDENCY_CYCLE",
                "Adding this dependency would create a cycle",
                http_status=409,
            )
        dep = TaskDependency(
            dependency_id=str(uuid.uuid4()),
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            soft=soft,
            created_at=utc_now(),
        )

        def _write(c: sqlite3.Connection) -> None:
            try:
                c.execute(
                    """
                    INSERT INTO task_dependencies(
                        dependency_id, task_id, depends_on_task_id, soft, created_at
                    ) VALUES (?,?,?,?,?)
                    """,
                    (dep.dependency_id, dep.task_id, dep.depends_on_task_id, 1 if soft else 0, dep.created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise TaskError(
                    "DEPENDENCY_EXISTS",
                    "Dependency already exists",
                    http_status=409,
                ) from exc

        if conn is not None:
            _write(conn)
            return dep
        with self.connect() as c:
            self._ensure_schema(c)
            _write(c)
        return dep

    def get_dependency(self, dependency_id: str) -> TaskDependency | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM task_dependencies WHERE dependency_id = ?",
                (dependency_id,),
            ).fetchone()
        return self._dep_from_row(row) if row else None

    def remove_dependency(self, dependency_id: str) -> bool:
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                "DELETE FROM task_dependencies WHERE dependency_id = ?",
                (dependency_id,),
            )
        return cur.rowcount > 0

    # ── Row helpers ─────────────────────────────────────────────────────────

    def _task_row_values(self, record: TaskRecord) -> tuple[Any, ...]:
        return (
            record.task_id,
            record.title,
            record.description,
            record.board_column.value,
            1 if record.blocked else 0,
            record.blocked_reason,
            record.blocked_reason_code,
            record.priority.value,
            json.dumps(list(record.tags)),
            record.project,
            record.assignee_type.value,
            record.assignee_id,
            record.assignee_name,
            record.due_at,
            record.planned_start_at,
            record.completed_at,
            record.progress,
            record.created_at,
            record.updated_at,
            record.archived_at,
            record.source_type.value,
            record.source_ref,
            record.execution_binding.value,
            record.job_id,
            record.workflow_id,
            record.mission_id,
            record.run_id,
            record.approval_id,
            record.schedule_id,
            record.capability_id,
            json.dumps(dict(record.capability_arguments)),
            record.mission_request,
            record.execution_state,
            record.execution_error,
            record.execution_phase,
            record.execution_attempt,
            record.execution_progress,
            record.execution_started_at,
            record.execution_finished_at,
            record.board_order,
            record.created_by,
            json.dumps(dict(record.metadata)),
        )

    def _task_from_row(self, row: sqlite3.Row) -> TaskRecord:
        g = row.__getitem__
        tags_raw = g("tags_json") or "[]"
        meta_raw = g("metadata_json") or "{}"
        args_raw = g("capability_arguments_json") or "{}"
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            tags = []
        try:
            metadata = json.loads(meta_raw)
        except json.JSONDecodeError:
            metadata = {}
        try:
            cap_args = json.loads(args_raw)
        except json.JSONDecodeError:
            cap_args = {}
        return TaskRecord(
            task_id=str(g("task_id")),
            title=str(g("title")),
            description=str(g("description") or ""),
            board_column=BoardColumn(str(g("board_column"))),
            blocked=bool(g("blocked")),
            blocked_reason=g("blocked_reason"),
            blocked_reason_code=g("blocked_reason_code"),
            priority=TaskPriority(str(g("priority"))),
            tags=list(tags) if isinstance(tags, list) else [],
            project=g("project"),
            assignee_type=AssigneeType(str(g("assignee_type") or "none")),
            assignee_id=g("assignee_id"),
            assignee_name=g("assignee_name"),
            due_at=g("due_at"),
            planned_start_at=g("planned_start_at"),
            completed_at=g("completed_at"),
            progress=g("progress"),
            created_at=str(g("created_at")),
            updated_at=str(g("updated_at")),
            archived_at=g("archived_at"),
            source_type=SourceType(str(g("source_type") or "manual")),
            source_ref=g("source_ref"),
            execution_binding=ExecutionBinding(str(g("execution_binding") or "manual")),
            job_id=g("job_id"),
            workflow_id=g("workflow_id"),
            mission_id=g("mission_id"),
            run_id=g("run_id"),
            approval_id=g("approval_id"),
            schedule_id=g("schedule_id"),
            capability_id=g("capability_id"),
            capability_arguments=dict(cap_args) if isinstance(cap_args, dict) else {},
            mission_request=g("mission_request"),
            execution_state=g("execution_state"),
            execution_error=g("execution_error"),
            execution_phase=g("execution_phase"),
            execution_attempt=g("execution_attempt"),
            execution_progress=g("execution_progress"),
            execution_started_at=g("execution_started_at"),
            execution_finished_at=g("execution_finished_at"),
            board_order=int(g("board_order") or 0),
            created_by=str(g("created_by") or "operator"),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )

    def _subtask_from_row(self, row: sqlite3.Row) -> TaskSubtask:
        return TaskSubtask(
            subtask_id=str(row["subtask_id"]),
            task_id=str(row["task_id"]),
            title=str(row["title"]),
            completed=bool(row["completed"]),
            completed_at=row["completed_at"],
            sort_order=int(row["sort_order"] or 0),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _note_from_row(self, row: sqlite3.Row) -> TaskNote:
        return TaskNote(
            note_id=str(row["note_id"]),
            task_id=str(row["task_id"]),
            body=str(row["body"]),
            author_type=str(row["author_type"] or "operator"),
            author_id=row["author_id"],
            author_name=row["author_name"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _dep_from_row(self, row: sqlite3.Row) -> TaskDependency:
        return TaskDependency(
            dependency_id=str(row["dependency_id"]),
            task_id=str(row["task_id"]),
            depends_on_task_id=str(row["depends_on_task_id"]),
            soft=bool(row["soft"]),
            created_at=str(row["created_at"]),
        )

    def _event_from_row(self, row: sqlite3.Row) -> TaskEvent:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        return TaskEvent(
            event_id=str(row["event_id"]),
            task_id=str(row["task_id"]),
            event_type=str(row["event_type"]),
            actor_type=str(row["actor_type"] or "system"),
            actor_id=row["actor_id"],
            source_type=row["source_type"],
            source_ref=row["source_ref"],
            payload=dict(payload) if isinstance(payload, dict) else {},
            created_at=str(row["created_at"]),
        )
