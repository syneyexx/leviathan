from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .events import EventRecord, EventType
from .states import InvalidRunTransition, RunState, validate_transition
from .types import RunRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStore:
    """SQLite-backed canonical Run + Event persistence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    parent_run_id TEXT,
                    user_request TEXT NOT NULL,
                    state TEXT NOT NULL,
                    intent TEXT,
                    complexity TEXT,
                    selected_model TEXT,
                    output TEXT,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_runs_conversation
                    ON runs(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_run_events_run
                    ON run_events(run_id, created_at);
                """
            )

    def create_run(
        self,
        *,
        user_request: str,
        conversation_id: str | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunRecord:
        now = utc_now()
        run = RunRecord(
            run_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            user_request=user_request,
            state=RunState.CREATED,
            intent=None,
            complexity=None,
            selected_model=None,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, conversation_id, parent_run_id, user_request, state,
                    intent, complexity, selected_model, output, error, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.conversation_id,
                    run.parent_run_id,
                    run.user_request,
                    run.state.value,
                    run.intent,
                    run.complexity,
                    run.selected_model,
                    run.output,
                    run.error,
                    json.dumps(run.metadata),
                    run.created_at,
                    run.updated_at,
                ),
            )
        self.append_event(run.run_id, EventType.RUN_CREATED, {"state": run.state.value})
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def transition(
        self,
        run_id: str,
        target: RunState,
        *,
        intent: str | None = None,
        complexity: str | None = None,
        selected_model: str | None = None,
        output: str | None = None,
        error: str | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> RunRecord:
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run_id: {run_id}")
        validate_transition(run.state, target)
        now = utc_now()
        metadata = dict(run.metadata)
        if metadata_update:
            metadata.update(metadata_update)

        next_intent = intent if intent is not None else run.intent
        next_complexity = complexity if complexity is not None else run.complexity
        next_model = selected_model if selected_model is not None else run.selected_model
        next_output = output if output is not None else run.output
        next_error = error if error is not None else run.error

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE runs SET
                    state = ?, intent = ?, complexity = ?, selected_model = ?,
                    output = ?, error = ?, metadata_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    target.value,
                    next_intent,
                    next_complexity,
                    next_model,
                    next_output,
                    next_error,
                    json.dumps(metadata),
                    now,
                    run_id,
                ),
            )

        event_type = EventType.STATE_CHANGED
        if target == RunState.COMPLETED:
            event_type = EventType.RUN_COMPLETED
        elif target == RunState.FAILED:
            event_type = EventType.RUN_FAILED
        elif target == RunState.CANCELLED:
            event_type = EventType.RUN_CANCELLED

        self.append_event(
            run_id,
            event_type,
            {
                "from": run.state.value,
                "to": target.value,
                "error": next_error,
            },
        )
        updated = self.get_run(run_id)
        assert updated is not None
        return updated

    def append_event(self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None) -> EventRecord:
        event = EventRecord(
            event_id=str(uuid.uuid4()),
            run_id=run_id,
            event_type=event_type,
            created_at=utc_now(),
            payload=payload or {},
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_events(event_id, run_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event.event_id, event.run_id, event.event_type.value, json.dumps(event.payload), event.created_at),
            )
        return event

    def list_events(self, run_id: str) -> list[EventRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, run_id, event_type, payload_json, created_at
                FROM run_events WHERE run_id = ? ORDER BY created_at ASC, event_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            EventRecord(
                event_id=row["event_id"],
                run_id=row["run_id"],
                event_type=EventType(row["event_type"]),
                created_at=row["created_at"],
                payload=json.loads(row["payload_json"] or "{}"),
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            conversation_id=row["conversation_id"],
            parent_run_id=row["parent_run_id"],
            user_request=row["user_request"],
            state=RunState(row["state"]),
            intent=row["intent"],
            complexity=row["complexity"],
            selected_model=row["selected_model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            output=row["output"],
            error=row["error"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )


# Re-export for callers that import InvalidRunTransition via store usage.
__all__ = ["InvalidRunTransition", "RunStore"]
