"""Workflow persistence — definitions, versions, executions in the CONTROL DB.

The legacy ``workflows`` table becomes the definition authority. Historical
one-shot rows are migrated into ``workflow_executions`` (preserving IDs) plus
a reusable definition/version pair. No second database file is created.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .graph import content_hash, default_layout_for_graph, steps_to_graph, validate_graph
from .types import (
    WorkflowDefinition,
    WorkflowDefinitionStatus,
    WorkflowEdgeDef,
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowGraph,
    WorkflowLayoutNode,
    WorkflowNodeDef,
    WorkflowRecord,
    WorkflowState,
    WorkflowStepDef,
    WorkflowVariableDef,
    WorkflowVersion,
    execution_to_legacy_state,
    legacy_to_execution_state,
    linear_steps_from_graph,
    steps_to_workflow_step_defs,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_ms(started: str | None, ended: str | None) -> int | None:
    a = _parse_iso(started)
    b = _parse_iso(ended)
    if a is None or b is None:
        return None
    return max(0, int((b - a).total_seconds() * 1000))


class WorkflowStore:
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
            self._migrate_legacy_rows(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                state TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 0,
                run_id TEXT,
                step_results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._ensure_columns(
            conn,
            "workflows",
            {
                "description": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT NOT NULL DEFAULT ''",
                "tags_json": "TEXT NOT NULL DEFAULT '[]'",
                "definition_status": "TEXT",
                "current_version": "INTEGER NOT NULL DEFAULT 1",
                "graph_json": "TEXT NOT NULL DEFAULT '{}'",
                "variables_json": "TEXT NOT NULL DEFAULT '[]'",
                "layout_json": "TEXT NOT NULL DEFAULT '[]'",
                "config_json": "TEXT NOT NULL DEFAULT '{}'",
                "trigger_bindings_json": "TEXT NOT NULL DEFAULT '[]'",
                "revision": "INTEGER NOT NULL DEFAULT 1",
                "record_kind": "TEXT NOT NULL DEFAULT 'legacy'",
            },
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_versions (
                workflow_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                graph_json TEXT NOT NULL,
                variables_json TEXT NOT NULL,
                config_json TEXT NOT NULL,
                layout_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT,
                change_summary TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                validation_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (workflow_id, version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_executions (
                execution_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_version INTEGER NOT NULL,
                state TEXT NOT NULL,
                trigger_source TEXT NOT NULL DEFAULT 'MANUAL',
                requested_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                duration_ms INTEGER,
                current_node_id TEXT,
                node_results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                root_job_id TEXT,
                child_job_ids_json TEXT NOT NULL DEFAULT '[]',
                run_id TEXT,
                input_snapshot_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                cursor_json TEXT NOT NULL DEFAULT '{}',
                name_snapshot TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_exec_workflow_created "
            "ON workflow_executions(workflow_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_exec_state_created "
            "ON workflow_executions(state, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_exec_created ON workflow_executions(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_def_status ON workflows(definition_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wf_versions_workflow ON workflow_versions(workflow_id, version DESC)"
        )

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _migrate_legacy_rows(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT * FROM workflows").fetchall()
        for row in rows:
            keys = set(row.keys()) if isinstance(row, sqlite3.Row) else set()
            record_kind = row["record_kind"] if "record_kind" in keys else "legacy"
            definition_status = row["definition_status"] if "definition_status" in keys else None
            if record_kind == "definition" and definition_status:
                continue
            # Already migrated execution mirror left behind? skip if execution exists
            old_id = row["workflow_id"]
            existing_exec = conn.execute(
                "SELECT 1 FROM workflow_executions WHERE execution_id = ?",
                (old_id,),
            ).fetchone()
            if existing_exec and record_kind == "definition":
                continue
            if existing_exec and definition_status:
                # Definition row already rewritten
                continue

            steps_raw = json.loads(row["steps_json"] or "[]")
            steps = [
                WorkflowStepDef(
                    step_id=str(item.get("step_id")),
                    capability_id=str(item.get("capability_id") or ""),
                    arguments=dict(item.get("arguments") or {}),
                    approval_id=item.get("approval_id"),
                )
                for item in steps_raw
            ]
            graph = steps_to_graph(steps)
            layout = default_layout_for_graph(graph)
            now = utc_now()
            legacy_state = WorkflowState(row["state"])
            exec_state = legacy_to_execution_state(legacy_state)
            # New definition id; preserve old id as execution_id for TaskService.
            definition_id = str(uuid.uuid4())
            status = (
                WorkflowDefinitionStatus.INACTIVE
                if legacy_state
                in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}
                else WorkflowDefinitionStatus.DRAFT
            )
            meta = json.loads(row["metadata_json"] or "{}")
            meta = dict(meta)
            meta["legacy_migrated_from"] = old_id
            ch = content_hash(graph=graph, variables=[], config={})
            # Insert execution with OLD id
            if not existing_exec:
                step_results = json.loads(row["step_results_json"] or "[]")
                started = row["created_at"]
                ended = (
                    row["updated_at"]
                    if exec_state
                    in {
                        WorkflowExecutionState.COMPLETED,
                        WorkflowExecutionState.FAILED,
                        WorkflowExecutionState.CANCELLED,
                    }
                    else None
                )
                cursor = {
                    "mode": "linear",
                    "current_step": int(row["current_step"] or 0),
                    "step_ids": [s.step_id for s in steps],
                }
                # Map step index → current node
                current_node = None
                if steps and int(row["current_step"] or 0) < len(steps):
                    current_node = steps[int(row["current_step"] or 0)].step_id
                elif steps and int(row["current_step"] or 0) >= len(steps):
                    current_node = steps[-1].step_id
                conn.execute(
                    """
                    INSERT INTO workflow_executions(
                        execution_id, workflow_id, workflow_version, state, trigger_source,
                        requested_by, created_at, updated_at, started_at, ended_at, duration_ms,
                        current_node_id, node_results_json, error, root_job_id, child_job_ids_json,
                        run_id, input_snapshot_json, metadata_json, cursor_json, name_snapshot
                    ) VALUES (?, ?, 1, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '[]', ?, '{}', ?, ?, ?)
                    """,
                    (
                        old_id,
                        definition_id,
                        exec_state.value,
                        "API",
                        row["created_at"],
                        row["updated_at"],
                        started,
                        ended,
                        _duration_ms(started, ended),
                        current_node,
                        json.dumps(step_results),
                        row["error"],
                        row["run_id"],
                        json.dumps(meta),
                        json.dumps(cursor),
                        row["name"],
                    ),
                )
            # Version
            conn.execute(
                """
                INSERT OR IGNORE INTO workflow_versions(
                    workflow_id, version, graph_json, variables_json, config_json, layout_json,
                    created_at, created_by, change_summary, content_hash, validation_json
                ) VALUES (?, 1, ?, '[]', '{}', ?, ?, 'migration', 'legacy linear import', ?, '{}')
                """,
                (
                    definition_id,
                    json.dumps(graph.public_dict()),
                    json.dumps([n.public_dict() for n in layout]),
                    row["created_at"] or now,
                    ch,
                ),
            )
            # Replace legacy row with definition row (new id)
            conn.execute("DELETE FROM workflows WHERE workflow_id = ?", (old_id,))
            conn.execute(
                """
                INSERT INTO workflows(
                    workflow_id, name, state, steps_json, created_at, updated_at,
                    current_step, run_id, step_results_json, error, metadata_json,
                    description, category, tags_json, definition_status, current_version,
                    graph_json, variables_json, layout_json, config_json, trigger_bindings_json,
                    revision, record_kind
                ) VALUES (?, ?, 'INACTIVE', ?, ?, ?, 0, NULL, '[]', NULL, ?, '', '', '[]', ?, 1, ?, '[]', ?, '{}', '[]', 1, 'definition')
                """,
                (
                    definition_id,
                    row["name"],
                    json.dumps([s.public_dict() for s in steps]),
                    row["created_at"],
                    row["updated_at"],
                    json.dumps(meta),
                    status.value,
                    json.dumps(graph.public_dict()),
                    json.dumps([n.public_dict() for n in layout]),
                ),
            )

    # ------------------------------------------------------------------
    # Legacy WorkflowRecord API (execution-addressed)
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        steps: list[WorkflowStepDef],
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        definition_status: WorkflowDefinitionStatus = WorkflowDefinitionStatus.INACTIVE,
        trigger_source: str = "API",
        requested_by: str | None = None,
        category: str = "",
        description: str = "",
    ) -> WorkflowRecord:
        if not steps:
            raise ValueError("Workflow requires at least one step")
        graph = steps_to_graph(steps)
        definition = self.create_definition(
            name=name,
            graph=graph,
            status=definition_status,
            run_id=run_id,
            metadata=metadata,
            category=category,
            description=description,
            create_initial_execution=True,
            trigger_source=trigger_source,
            requested_by=requested_by,
        )
        # Initial execution uses a fresh id; locate it.
        executions = self.list_executions(workflow_id=definition.workflow_id, limit=1)
        if not executions:
            raise RuntimeError("Failed to create initial workflow execution")
        return self._record_from_execution(executions[0], definition)

    def get(self, workflow_id: str) -> WorkflowRecord | None:
        """Resolve by execution_id first (legacy), then definition_id."""
        execution = self.get_execution(workflow_id)
        if execution is not None:
            definition = self.get_definition(execution.workflow_id)
            return self._record_from_execution(execution, definition)
        definition = self.get_definition(workflow_id)
        if definition is None:
            return None
        # Definition-only: synthesize a CREATED record for inspection (no execution).
        steps = steps_to_workflow_step_defs(linear_steps_from_graph(definition.graph))
        return WorkflowRecord(
            workflow_id=definition.workflow_id,
            name=definition.name,
            state=WorkflowState.CREATED,
            steps=steps,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
            definition_id=definition.workflow_id,
            definition_status=definition.status.value,
            workflow_version=definition.current_version,
            metadata=dict(definition.metadata),
        )

    def list(self, *, limit: int = 100, offset: int = 0) -> list[WorkflowRecord]:
        """Legacy list: recent executions projected as WorkflowRecords."""
        executions = self.list_executions(limit=limit, offset=offset)
        out: list[WorkflowRecord] = []
        for execution in executions:
            definition = self.get_definition(execution.workflow_id)
            out.append(self._record_from_execution(execution, definition))
        return out

    def save(self, record: WorkflowRecord) -> WorkflowRecord:
        """Persist execution-facing fields for a WorkflowRecord (legacy runtime)."""
        execution = self.get_execution(record.workflow_id)
        if execution is None and record.execution_id:
            execution = self.get_execution(record.execution_id)
        if execution is None:
            # Fall back: treat as definition-only metadata update
            definition = self.get_definition(record.workflow_id)
            if definition is None:
                raise KeyError(record.workflow_id)
            definition.metadata = dict(record.metadata or {})
            definition.updated_at = utc_now()
            self._upsert_definition(definition)
            return record

        execution.state = legacy_to_execution_state(record.state)
        execution.error = record.error
        execution.run_id = record.run_id
        execution.node_results = list(record.step_results or [])
        execution.metadata = dict(record.metadata or {})
        cursor = dict(execution.cursor or {})
        cursor["current_step"] = int(record.current_step)
        cursor["mode"] = cursor.get("mode") or "linear"
        step_ids = [s.step_id for s in record.steps]
        cursor["step_ids"] = step_ids
        execution.cursor = cursor
        if step_ids and 0 <= record.current_step < len(step_ids):
            execution.current_node_id = step_ids[record.current_step]
        if execution.state == WorkflowExecutionState.RUNNING and not execution.started_at:
            execution.started_at = utc_now()
        if execution.state in {
            WorkflowExecutionState.COMPLETED,
            WorkflowExecutionState.FAILED,
            WorkflowExecutionState.CANCELLED,
        }:
            execution.ended_at = execution.ended_at or utc_now()
            execution.duration_ms = _duration_ms(execution.started_at or execution.created_at, execution.ended_at)
        execution.updated_at = utc_now()
        self._upsert_execution(execution)
        record.updated_at = execution.updated_at
        return record

    # ------------------------------------------------------------------
    # Definitions
    # ------------------------------------------------------------------

    def create_definition(
        self,
        *,
        name: str,
        graph: WorkflowGraph | None = None,
        steps: list[WorkflowStepDef] | None = None,
        status: WorkflowDefinitionStatus = WorkflowDefinitionStatus.DRAFT,
        description: str = "",
        category: str = "",
        tags: list[str] | None = None,
        variables: list[WorkflowVariableDef] | None = None,
        layout: list[WorkflowLayoutNode] | None = None,
        config: dict[str, Any] | None = None,
        trigger_bindings: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        created_by: str | None = None,
        create_initial_execution: bool = False,
        trigger_source: str = "MANUAL",
        requested_by: str | None = None,
        workflow_id: str | None = None,
    ) -> WorkflowDefinition:
        if graph is None:
            if not steps:
                graph = steps_to_graph([])
            else:
                graph = steps_to_graph(steps)
        now = utc_now()
        layout = layout or default_layout_for_graph(graph)
        variables = variables or []
        config = config or {}
        definition = WorkflowDefinition(
            workflow_id=workflow_id or str(uuid.uuid4()),
            name=(name or "").strip() or "workflow",
            status=status,
            created_at=now,
            updated_at=now,
            description=description,
            category=category,
            tags=list(tags or []),
            current_version=1,
            graph=graph,
            variables=list(variables),
            layout=list(layout),
            config=dict(config),
            trigger_bindings=list(trigger_bindings or []),
            revision=1,
            metadata=dict(metadata or {}),
        )
        if run_id:
            definition.metadata["run_id"] = run_id
        validation = validate_graph(graph, variables=variables, allow_draft_warnings=True)
        ch = content_hash(graph=graph, variables=variables, config=config)
        version = WorkflowVersion(
            workflow_id=definition.workflow_id,
            version=1,
            graph=graph,
            variables=list(variables),
            config=dict(config),
            layout=list(layout),
            created_at=now,
            created_by=created_by,
            change_summary="initial",
            content_hash=ch,
            validation=validation,
        )
        with self.connect() as conn:
            self._insert_definition_conn(conn, definition)
            self._insert_version_conn(conn, version)
            if create_initial_execution:
                execution = self._new_execution(
                    definition=definition,
                    version=1,
                    trigger_source=trigger_source,
                    requested_by=requested_by,
                    run_id=run_id,
                    graph=graph,
                )
                self._insert_execution_conn(conn, execution)
        return definition

    def get_definition(self, workflow_id: str) -> WorkflowDefinition | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id = ? AND record_kind = 'definition'",
                (workflow_id,),
            ).fetchone()
            if row is None:
                # Also accept rows that have definition_status set (post-alter, pre-kind).
                row = conn.execute(
                    "SELECT * FROM workflows WHERE workflow_id = ? AND definition_status IS NOT NULL",
                    (workflow_id,),
                ).fetchone()
        return self._definition_from_row(row) if row else None

    def list_definitions(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        status: str | None = None,
        category: str | None = None,
        query: str | None = None,
        include_templates: bool = True,
        include_archived: bool = False,
    ) -> list[WorkflowDefinition]:
        clauses = ["(record_kind = 'definition' OR definition_status IS NOT NULL)"]
        params: list[Any] = []
        if status:
            clauses.append("definition_status = ?")
            params.append(status)
        elif not include_archived:
            clauses.append("(definition_status IS NULL OR definition_status != 'ARCHIVED')")
        if not include_templates and not status:
            clauses.append("(definition_status IS NULL OR definition_status != 'TEMPLATE')")
        if category:
            clauses.append("category = ?")
            params.append(category)
        if query:
            q = f"%{query.strip().lower()}%"
            clauses.append(
                "(lower(name) LIKE ? OR lower(COALESCE(description,'')) LIKE ? "
                "OR lower(COALESCE(category,'')) LIKE ? OR lower(COALESCE(tags_json,'')) LIKE ?)"
            )
            params.extend([q, q, q, q])
        sql = (
            "SELECT * FROM workflows WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, workflow_id LIMIT ? OFFSET ?"
        )
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._definition_from_row(row) for row in rows]

    def save_definition(
        self,
        definition: WorkflowDefinition,
        *,
        expected_revision: int | None = None,
        create_version: bool = True,
        change_summary: str = "",
        created_by: str | None = None,
    ) -> WorkflowDefinition:
        current = self.get_definition(definition.workflow_id)
        if current is None:
            raise KeyError(definition.workflow_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise ValueError("WORKFLOW_VERSION_CONFLICT")
        definition.updated_at = utc_now()
        definition.revision = int(current.revision) + 1
        ch = content_hash(
            graph=definition.graph,
            variables=definition.variables,
            config=definition.config,
        )
        latest = self.get_version(definition.workflow_id, current.current_version)
        should_version = create_version and (latest is None or latest.content_hash != ch)
        if should_version:
            definition.current_version = int(current.current_version) + 1
            version = WorkflowVersion(
                workflow_id=definition.workflow_id,
                version=definition.current_version,
                graph=definition.graph,
                variables=list(definition.variables),
                config=dict(definition.config),
                layout=list(definition.layout),
                created_at=definition.updated_at,
                created_by=created_by,
                change_summary=change_summary or "update",
                content_hash=ch,
                validation=validate_graph(definition.graph, variables=definition.variables),
            )
            with self.connect() as conn:
                self._insert_definition_conn(conn, definition, replace=True)
                self._insert_version_conn(conn, version)
        else:
            definition.current_version = current.current_version
            with self.connect() as conn:
                self._insert_definition_conn(conn, definition, replace=True)
        return definition

    def delete_definition(self, workflow_id: str, *, hard: bool = False) -> None:
        active = self.list_executions(
            workflow_id=workflow_id,
            states=[
                WorkflowExecutionState.QUEUED.value,
                WorkflowExecutionState.STARTING.value,
                WorkflowExecutionState.RUNNING.value,
                WorkflowExecutionState.WAITING.value,
                WorkflowExecutionState.WAITING_APPROVAL.value,
                WorkflowExecutionState.CANCELLING.value,
            ],
            limit=1,
        )
        if active:
            raise ValueError("Cannot delete workflow while an execution is active")
        if hard:
            with self.connect() as conn:
                conn.execute("DELETE FROM workflow_versions WHERE workflow_id = ?", (workflow_id,))
                conn.execute("DELETE FROM workflows WHERE workflow_id = ?", (workflow_id,))
            return
        definition = self.get_definition(workflow_id)
        if definition is None:
            raise KeyError(workflow_id)
        definition.status = WorkflowDefinitionStatus.ARCHIVED
        definition.updated_at = utc_now()
        definition.revision += 1
        self._upsert_definition(definition)

    def duplicate_definition(
        self,
        workflow_id: str,
        *,
        name: str | None = None,
        created_by: str | None = None,
    ) -> WorkflowDefinition:
        source = self.get_definition(workflow_id)
        if source is None:
            raise KeyError(workflow_id)
        status = (
            WorkflowDefinitionStatus.DRAFT
            if source.status == WorkflowDefinitionStatus.TEMPLATE
            else WorkflowDefinitionStatus.INACTIVE
        )
        return self.create_definition(
            name=name or f"Kopie van {source.name}",
            graph=WorkflowGraph(
                nodes=list(source.graph.nodes),
                edges=list(source.graph.edges),
            ),
            status=status,
            description=source.description,
            category=source.category,
            tags=list(source.tags),
            variables=[
                WorkflowVariableDef(
                    name=v.name,
                    var_type=v.var_type,
                    default=None if v.secret else v.default,
                    required=v.required,
                    description=v.description,
                    secret=v.secret,
                )
                for v in source.variables
            ],
            layout=list(source.layout),
            config=dict(source.config),
            trigger_bindings=[],  # do not copy automatic triggers
            metadata={"duplicated_from": workflow_id},
            created_by=created_by,
        )

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def get_version(self, workflow_id: str, version: int) -> WorkflowVersion | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? AND version = ?",
                (workflow_id, version),
            ).fetchone()
        return self._version_from_row(row) if row else None

    def list_versions(self, workflow_id: str, *, limit: int = 50) -> list[WorkflowVersion]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? "
                "ORDER BY version DESC LIMIT ?",
                (workflow_id, max(1, min(limit, 200))),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def restore_version(
        self,
        workflow_id: str,
        version: int,
        *,
        created_by: str | None = None,
    ) -> WorkflowDefinition:
        prior = self.get_version(workflow_id, version)
        if prior is None:
            raise KeyError(f"Unknown version {version}")
        definition = self.get_definition(workflow_id)
        if definition is None:
            raise KeyError(workflow_id)
        definition.graph = prior.graph
        definition.variables = list(prior.variables)
        definition.config = dict(prior.config)
        definition.layout = list(prior.layout)
        return self.save_definition(
            definition,
            create_version=True,
            change_summary=f"restore version {version}",
            created_by=created_by,
        )

    # ------------------------------------------------------------------
    # Executions
    # ------------------------------------------------------------------

    def create_execution(
        self,
        *,
        workflow_id: str,
        version: int | None = None,
        trigger_source: str = "MANUAL",
        requested_by: str | None = None,
        run_id: str | None = None,
        input_snapshot: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> WorkflowExecution:
        definition = self.get_definition(workflow_id)
        if definition is None:
            raise KeyError(workflow_id)
        ver = int(version or definition.current_version)
        if self.get_version(workflow_id, ver) is None:
            raise KeyError(f"Unknown workflow version {ver}")
        execution = self._new_execution(
            definition=definition,
            version=ver,
            trigger_source=trigger_source,
            requested_by=requested_by,
            run_id=run_id,
            input_snapshot=input_snapshot,
            metadata=metadata,
            execution_id=execution_id,
        )
        self._upsert_execution(execution)
        return execution

    def get_execution(self, execution_id: str) -> WorkflowExecution | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return self._execution_from_row(row) if row else None

    def list_executions(
        self,
        *,
        workflow_id: str | None = None,
        states: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        since: str | None = None,
        until: str | None = None,
    ) -> list[WorkflowExecution]:
        clauses: list[str] = []
        params: list[Any] = []
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if states:
            placeholders = ",".join("?" for _ in states)
            clauses.append(f"state IN ({placeholders})")
            params.extend(states)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at < ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM workflow_executions{where} "
            "ORDER BY created_at DESC, execution_id LIMIT ? OFFSET ?"
        )
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._execution_from_row(row) for row in rows]

    def save_execution(self, execution: WorkflowExecution) -> WorkflowExecution:
        execution.updated_at = utc_now()
        if execution.state in {
            WorkflowExecutionState.COMPLETED,
            WorkflowExecutionState.FAILED,
            WorkflowExecutionState.CANCELLED,
        }:
            execution.ended_at = execution.ended_at or execution.updated_at
            execution.duration_ms = _duration_ms(
                execution.started_at or execution.created_at,
                execution.ended_at,
            )
        self._upsert_execution(execution)
        return execution

    def count_definitions(
        self,
        *,
        status: str | None = None,
        exclude_templates: bool = True,
        exclude_archived: bool = True,
    ) -> int:
        clauses = ["(record_kind = 'definition' OR definition_status IS NOT NULL)"]
        params: list[Any] = []
        if status:
            clauses.append("definition_status = ?")
            params.append(status)
        else:
            if exclude_templates:
                clauses.append("(definition_status IS NULL OR definition_status != 'TEMPLATE')")
            if exclude_archived:
                clauses.append("(definition_status IS NULL OR definition_status != 'ARCHIVED')")
        sql = "SELECT COUNT(*) AS c FROM workflows WHERE " + " AND ".join(clauses)
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0] if not isinstance(row, sqlite3.Row) else row["c"])

    def count_executions(
        self,
        *,
        workflow_id: str | None = None,
        states: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if states:
            placeholders = ",".join("?" for _ in states)
            clauses.append(f"state IN ({placeholders})")
            params.extend(states)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at < ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM workflow_executions{where}", params).fetchone()
        return int(row[0] if not isinstance(row, sqlite3.Row) else row["c"])

    def aggregate_execution_stats(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at < ?")
            params.append(until)
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT
              SUM(CASE WHEN state = 'COMPLETED' THEN 1 ELSE 0 END) AS succeeded,
              SUM(CASE WHEN state = 'FAILED' THEN 1 ELSE 0 END) AS failed,
              SUM(CASE WHEN state = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
              SUM(CASE WHEN state IN ('QUEUED','STARTING','RUNNING','WAITING','WAITING_APPROVAL','CANCELLING') THEN 1 ELSE 0 END) AS running,
              COUNT(*) AS total,
              AVG(CASE WHEN duration_ms IS NOT NULL AND state IN ('COMPLETED','FAILED','CANCELLED') THEN duration_ms END) AS avg_duration_ms
            FROM workflow_executions{where}
        """
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        succeeded = int(row["succeeded"] or 0)
        failed = int(row["failed"] or 0)
        denom = succeeded + failed
        success_rate = (succeeded / denom) if denom else None
        return {
            "succeeded": succeeded,
            "failed": failed,
            "cancelled": int(row["cancelled"] or 0),
            "running": int(row["running"] or 0),
            "total": int(row["total"] or 0),
            "avg_duration_ms": float(row["avg_duration_ms"]) if row["avg_duration_ms"] is not None else None,
            "success_rate": success_rate,
            "success_rate_denominator": "successful / (successful + failed)",
        }

    def execution_time_buckets(
        self,
        *,
        since: str,
        until: str,
        bucket_seconds: int = 3600,
    ) -> list[dict[str, Any]]:
        bucket_seconds = max(60, int(bucket_seconds))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, state FROM workflow_executions
                WHERE created_at >= ? AND created_at < ?
                ORDER BY created_at ASC
                """,
                (since, until),
            ).fetchall()
        start = _parse_iso(since)
        end = _parse_iso(until)
        if start is None or end is None:
            return []
        buckets: dict[int, dict[str, Any]] = {}
        cursor = start
        idx = 0
        while cursor < end:
            buckets[idx] = {
                "bucket_start": cursor.isoformat(),
                "succeeded": 0,
                "failed": 0,
                "cancelled": 0,
            }
            from datetime import timedelta

            cursor = cursor + timedelta(seconds=bucket_seconds)
            idx += 1
        for row in rows:
            ts = _parse_iso(row["created_at"])
            if ts is None:
                continue
            offset = int((ts - start).total_seconds() // bucket_seconds)
            if offset not in buckets:
                continue
            state = row["state"]
            if state == "COMPLETED":
                buckets[offset]["succeeded"] += 1
            elif state == "FAILED":
                buckets[offset]["failed"] += 1
            elif state == "CANCELLED":
                buckets[offset]["cancelled"] += 1
        return [buckets[i] for i in sorted(buckets)]

    def top_workflows_by_executions(
        self,
        *,
        since: str,
        until: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        clauses = ["e.created_at >= ?"]
        params: list[Any] = [since]
        if until:
            clauses.append("e.created_at < ?")
            params.append(until)
        where = " AND ".join(clauses)
        params.append(max(1, min(limit, 50)))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.workflow_id AS workflow_id, COUNT(*) AS execution_count,
                       COALESCE(MAX(w.name), MAX(e.name_snapshot), e.workflow_id) AS name
                FROM workflow_executions e
                LEFT JOIN workflows w ON w.workflow_id = e.workflow_id
                WHERE {where}
                GROUP BY e.workflow_id
                ORDER BY execution_count DESC, name ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "workflow_id": row["workflow_id"],
                "name": row["name"],
                "execution_count": int(row["execution_count"]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _new_execution(
        self,
        *,
        definition: WorkflowDefinition,
        version: int,
        trigger_source: str,
        requested_by: str | None,
        run_id: str | None = None,
        input_snapshot: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        execution_id: str | None = None,
        graph: WorkflowGraph | None = None,
    ) -> WorkflowExecution:
        now = utc_now()
        if graph is None:
            ver = self.get_version(definition.workflow_id, version)
            graph = ver.graph if ver else definition.graph
        step_ids = [s["step_id"] for s in linear_steps_from_graph(graph)]
        # Prefer trigger as entry; graph runtime walks edges from there.
        trigger = next((n for n in graph.nodes if n.kind_value == "trigger"), None)
        start_node = trigger.node_id if trigger else (graph.nodes[0].node_id if graph.nodes else None)
        return WorkflowExecution(
            execution_id=execution_id or str(uuid.uuid4()),
            workflow_id=definition.workflow_id,
            workflow_version=version,
            state=WorkflowExecutionState.QUEUED,
            created_at=now,
            updated_at=now,
            trigger_source=trigger_source,
            requested_by=requested_by,
            run_id=run_id,
            input_snapshot=dict(input_snapshot or {}),
            metadata=dict(metadata or {}),
            current_node_id=start_node,
            cursor={
                "mode": "graph",
                "current_step": 0,
                "step_ids": step_ids,
                "current_node_id": start_node,
                "visited": [],
                "loop_counters": {},
            },
            name_snapshot=definition.name,
        )

    def _record_from_execution(
        self,
        execution: WorkflowExecution,
        definition: WorkflowDefinition | None,
    ) -> WorkflowRecord:
        version = self.get_version(execution.workflow_id, execution.workflow_version)
        if version is not None:
            steps = steps_to_workflow_step_defs(linear_steps_from_graph(version.graph))
        elif definition is not None:
            steps = steps_to_workflow_step_defs(linear_steps_from_graph(definition.graph))
        else:
            steps = []
        cursor = dict(execution.cursor or {})
        current_step = int(cursor.get("current_step") or 0)
        # Prefer node_results excluding non-executable trigger markers for legacy step_results.
        step_results = [
            r
            for r in list(execution.node_results or [])
            if r.get("kind") != "trigger"
        ]
        name = (
            (definition.name if definition else None)
            or str(getattr(execution, "name_snapshot", "") or "")
            or execution.workflow_id
        )
        meta = dict(execution.metadata or {})
        meta["definition_id"] = execution.workflow_id
        meta["execution_id"] = execution.execution_id
        meta["workflow_version"] = execution.workflow_version
        if execution.state == WorkflowExecutionState.WAITING:
            meta.setdefault("wait_reason", "WAITING_CHILD")
        if execution.state == WorkflowExecutionState.WAITING_APPROVAL:
            meta.setdefault("wait_reason", "WAITING_APPROVAL")
        return WorkflowRecord(
            workflow_id=execution.execution_id,  # legacy address = execution
            name=name,
            state=execution_to_legacy_state(execution.state),
            steps=steps,
            created_at=execution.created_at,
            updated_at=execution.updated_at,
            current_step=current_step,
            run_id=execution.run_id,
            step_results=step_results,
            error=execution.error,
            metadata=meta,
            definition_id=execution.workflow_id,
            execution_id=execution.execution_id,
            workflow_version=execution.workflow_version,
            definition_status=definition.status.value if definition else None,
        )

    def _upsert_definition(self, definition: WorkflowDefinition) -> None:
        with self.connect() as conn:
            self._insert_definition_conn(conn, definition, replace=True)

    def _upsert_execution(self, execution: WorkflowExecution) -> None:
        with self.connect() as conn:
            self._insert_execution_conn(conn, execution, replace=True)

    def _insert_definition_conn(
        self,
        conn: sqlite3.Connection,
        definition: WorkflowDefinition,
        *,
        replace: bool = False,
    ) -> None:
        steps = linear_steps_from_graph(definition.graph)
        sql = """
            INSERT OR REPLACE INTO workflows(
                workflow_id, name, state, steps_json, created_at, updated_at,
                current_step, run_id, step_results_json, error, metadata_json,
                description, category, tags_json, definition_status, current_version,
                graph_json, variables_json, layout_json, config_json, trigger_bindings_json,
                revision, record_kind
            ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, '[]', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'definition')
        """ if replace else """
            INSERT INTO workflows(
                workflow_id, name, state, steps_json, created_at, updated_at,
                current_step, run_id, step_results_json, error, metadata_json,
                description, category, tags_json, definition_status, current_version,
                graph_json, variables_json, layout_json, config_json, trigger_bindings_json,
                revision, record_kind
            ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, '[]', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'definition')
        """
        # Use DELETE+INSERT for replace to avoid OR REPLACE wiping differently
        if replace:
            conn.execute("DELETE FROM workflows WHERE workflow_id = ?", (definition.workflow_id,))
            sql = sql.replace("INSERT OR REPLACE", "INSERT")
        conn.execute(
            sql,
            (
                definition.workflow_id,
                definition.name,
                definition.status.value,
                json.dumps(steps),
                definition.created_at,
                definition.updated_at,
                json.dumps(definition.metadata),
                definition.description,
                definition.category,
                json.dumps(definition.tags),
                definition.status.value,
                definition.current_version,
                json.dumps(definition.graph.public_dict()),
                json.dumps([v.public_dict() for v in definition.variables]),
                json.dumps([n.public_dict() for n in definition.layout]),
                json.dumps(definition.config),
                json.dumps(definition.trigger_bindings),
                definition.revision,
            ),
        )

    def _insert_version_conn(self, conn: sqlite3.Connection, version: WorkflowVersion) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO workflow_versions(
                workflow_id, version, graph_json, variables_json, config_json, layout_json,
                created_at, created_by, change_summary, content_hash, validation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.workflow_id,
                version.version,
                json.dumps(version.graph.public_dict()),
                json.dumps([v.public_dict() for v in version.variables]),
                json.dumps(version.config),
                json.dumps([n.public_dict() for n in version.layout]),
                version.created_at,
                version.created_by,
                version.change_summary,
                version.content_hash,
                json.dumps(version.validation),
            ),
        )

    def _insert_execution_conn(
        self,
        conn: sqlite3.Connection,
        execution: WorkflowExecution,
        *,
        replace: bool = False,
    ) -> None:
        if replace:
            conn.execute("DELETE FROM workflow_executions WHERE execution_id = ?", (execution.execution_id,))
        conn.execute(
            """
            INSERT INTO workflow_executions(
                execution_id, workflow_id, workflow_version, state, trigger_source,
                requested_by, created_at, updated_at, started_at, ended_at, duration_ms,
                current_node_id, node_results_json, error, root_job_id, child_job_ids_json,
                run_id, input_snapshot_json, metadata_json, cursor_json, name_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution.execution_id,
                execution.workflow_id,
                execution.workflow_version,
                execution.state.value,
                execution.trigger_source,
                execution.requested_by,
                execution.created_at,
                execution.updated_at,
                execution.started_at,
                execution.ended_at,
                execution.duration_ms,
                execution.current_node_id,
                json.dumps(execution.node_results),
                execution.error,
                execution.root_job_id,
                json.dumps(execution.child_job_ids),
                execution.run_id,
                json.dumps(execution.input_snapshot),
                json.dumps(execution.metadata),
                json.dumps(execution.cursor),
                getattr(execution, "name_snapshot", "") or "",
            ),
        )

    @staticmethod
    def _definition_from_row(row: sqlite3.Row) -> WorkflowDefinition:
        keys = set(row.keys())
        graph_raw = json.loads(row["graph_json"] or "{}") if "graph_json" in keys else {}
        if not graph_raw or not graph_raw.get("nodes"):
            steps_raw = json.loads(row["steps_json"] or "[]")
            steps = [
                WorkflowStepDef(
                    step_id=str(item.get("step_id")),
                    capability_id=str(item.get("capability_id") or ""),
                    arguments=dict(item.get("arguments") or {}),
                    approval_id=item.get("approval_id"),
                )
                for item in steps_raw
            ]
            graph = steps_to_graph(steps)
        else:
            graph = WorkflowGraph.from_dict(graph_raw)
        status_raw = row["definition_status"] if "definition_status" in keys and row["definition_status"] else row["state"]
        try:
            status = WorkflowDefinitionStatus(status_raw)
        except ValueError:
            status = WorkflowDefinitionStatus.INACTIVE
        variables = [
            WorkflowVariableDef.from_dict(v)
            for v in json.loads(row["variables_json"] or "[]") if "variables_json" in keys
        ] if "variables_json" in keys else []
        layout = [
            WorkflowLayoutNode(node_id=str(n["node_id"]), x=float(n.get("x") or 0), y=float(n.get("y") or 0))
            for n in (json.loads(row["layout_json"] or "[]") if "layout_json" in keys else [])
        ]
        return WorkflowDefinition(
            workflow_id=row["workflow_id"],
            name=row["name"],
            status=status,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            description=row["description"] if "description" in keys else "",
            category=row["category"] if "category" in keys else "",
            tags=json.loads(row["tags_json"] or "[]") if "tags_json" in keys else [],
            current_version=int(row["current_version"] or 1) if "current_version" in keys else 1,
            graph=graph,
            variables=variables,
            layout=layout,
            config=json.loads(row["config_json"] or "{}") if "config_json" in keys else {},
            trigger_bindings=json.loads(row["trigger_bindings_json"] or "[]")
            if "trigger_bindings_json" in keys
            else [],
            revision=int(row["revision"] or 1) if "revision" in keys else 1,
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _version_from_row(row: sqlite3.Row) -> WorkflowVersion:
        return WorkflowVersion(
            workflow_id=row["workflow_id"],
            version=int(row["version"]),
            graph=WorkflowGraph.from_dict(json.loads(row["graph_json"] or "{}")),
            variables=[WorkflowVariableDef.from_dict(v) for v in json.loads(row["variables_json"] or "[]")],
            config=json.loads(row["config_json"] or "{}"),
            layout=[
                WorkflowLayoutNode(node_id=str(n["node_id"]), x=float(n.get("x") or 0), y=float(n.get("y") or 0))
                for n in json.loads(row["layout_json"] or "[]")
            ],
            created_at=row["created_at"],
            created_by=row["created_by"],
            change_summary=row["change_summary"] or "",
            content_hash=row["content_hash"] or "",
            validation=json.loads(row["validation_json"] or "{}"),
        )

    @staticmethod
    def _execution_from_row(row: sqlite3.Row) -> WorkflowExecution:
        keys = set(row.keys())
        execution = WorkflowExecution(
            execution_id=row["execution_id"],
            workflow_id=row["workflow_id"],
            workflow_version=int(row["workflow_version"]),
            state=WorkflowExecutionState(row["state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            trigger_source=row["trigger_source"] or "MANUAL",
            requested_by=row["requested_by"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_ms=row["duration_ms"],
            current_node_id=row["current_node_id"],
            node_results=json.loads(row["node_results_json"] or "[]"),
            error=row["error"],
            root_job_id=row["root_job_id"],
            child_job_ids=json.loads(row["child_job_ids_json"] or "[]"),
            run_id=row["run_id"],
            input_snapshot=json.loads(row["input_snapshot_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            cursor=json.loads(row["cursor_json"] or "{}"),
        )
        if "name_snapshot" in keys:
            setattr(execution, "name_snapshot", row["name_snapshot"] or "")
        return execution

    # Keep old static helper name used by tests/tools
    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowRecord:
        """Deprecated path for raw legacy rows — prefer get()/get_execution()."""
        steps_raw = json.loads(row["steps_json"] or "[]")
        steps = [
            WorkflowStepDef(
                step_id=str(item.get("step_id")),
                capability_id=str(item.get("capability_id")),
                arguments=dict(item.get("arguments") or {}),
                approval_id=item.get("approval_id"),
            )
            for item in steps_raw
        ]
        return WorkflowRecord(
            workflow_id=row["workflow_id"],
            name=row["name"],
            state=WorkflowState(row["state"]),
            steps=steps,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            current_step=int(row["current_step"]),
            run_id=row["run_id"],
            step_results=json.loads(row["step_results_json"] or "[]"),
            error=row["error"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
