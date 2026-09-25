from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import WorkflowRecord, WorkflowState, WorkflowStepDef


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

    def create(
        self,
        *,
        name: str,
        steps: list[WorkflowStepDef],
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowRecord:
        if not steps:
            raise ValueError("Workflow requires at least one step")
        now = utc_now()
        record = WorkflowRecord(
            workflow_id=str(uuid.uuid4()),
            name=name.strip() or "workflow",
            state=WorkflowState.CREATED,
            steps=list(steps),
            created_at=now,
            updated_at=now,
            run_id=run_id,
            metadata=metadata or {},
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows(
                    workflow_id, name, state, steps_json, created_at, updated_at,
                    current_step, run_id, step_results_json, error, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, '[]', NULL, ?)
                """,
                (
                    record.workflow_id,
                    record.name,
                    record.state.value,
                    json.dumps([s.public_dict() for s in record.steps]),
                    record.created_at,
                    record.updated_at,
                    record.run_id,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def get(self, workflow_id: str) -> WorkflowRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, limit: int = 100) -> list[WorkflowRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflows ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, record: WorkflowRecord) -> WorkflowRecord:
        record.updated_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE workflows SET
                    state = ?, current_step = ?, step_results_json = ?,
                    error = ?, updated_at = ?, metadata_json = ?
                WHERE workflow_id = ?
                """,
                (
                    record.state.value,
                    record.current_step,
                    json.dumps(record.step_results),
                    record.error,
                    record.updated_at,
                    json.dumps(record.metadata),
                    record.workflow_id,
                ),
            )
        return record

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowRecord:
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
