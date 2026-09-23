from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.correlation import new_id

from .events import EventRecord, EventType
from .envelope import EVENT_ENVELOPE_SCHEMA_VERSION
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
            self._ensure_wave0_columns(conn)

    def _ensure_wave0_columns(self, conn: sqlite3.Connection) -> None:
        run_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        run_alters = {
            "trace_id": "ALTER TABLE runs ADD COLUMN trace_id TEXT",
            "attempt_number": "ALTER TABLE runs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1",
            "transition_reason": "ALTER TABLE runs ADD COLUMN transition_reason TEXT",
            "cancellation_cause": "ALTER TABLE runs ADD COLUMN cancellation_cause TEXT",
            "retryable": "ALTER TABLE runs ADD COLUMN retryable INTEGER",
            "recovery_metadata_json": (
                "ALTER TABLE runs ADD COLUMN recovery_metadata_json TEXT NOT NULL DEFAULT '{}'"
            ),
        }
        for name, sql in run_alters.items():
            if name not in run_cols:
                conn.execute(sql)

        event_cols = {row[1] for row in conn.execute("PRAGMA table_info(run_events)").fetchall()}
        event_alters = {
            "trace_id": "ALTER TABLE run_events ADD COLUMN trace_id TEXT",
            "job_id": "ALTER TABLE run_events ADD COLUMN job_id TEXT",
            "actor": "ALTER TABLE run_events ADD COLUMN actor TEXT",
            "causal_parent": "ALTER TABLE run_events ADD COLUMN causal_parent TEXT",
            "schema_version": (
                "ALTER TABLE run_events ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
            ),
            "artifact_refs_json": (
                "ALTER TABLE run_events ADD COLUMN artifact_refs_json TEXT NOT NULL DEFAULT '[]'"
            ),
            "evidence_refs_json": (
                "ALTER TABLE run_events ADD COLUMN evidence_refs_json TEXT NOT NULL DEFAULT '[]'"
            ),
        }
        for name, sql in event_alters.items():
            if name not in event_cols:
                conn.execute(sql)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_events_trace ON run_events(trace_id, created_at)"
        )

    def create_run(
        self,
        *,
        user_request: str,
        conversation_id: str | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        attempt_number: int = 1,
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
            trace_id=trace_id or new_id("tr_"),
            attempt_number=max(1, int(attempt_number)),
        )
        with self.connect() as conn:
            self._ensure_wave0_columns(conn)
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, conversation_id, parent_run_id, user_request, state,
                    intent, complexity, selected_model, output, error, metadata_json,
                    created_at, updated_at, trace_id, attempt_number, transition_reason,
                    cancellation_cause, retryable, recovery_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.trace_id,
                    run.attempt_number,
                    run.transition_reason,
                    run.cancellation_cause,
                    None if run.retryable is None else int(run.retryable),
                    json.dumps(run.recovery_metadata),
                ),
            )
        self.append_event(
            run.run_id,
            EventType.RUN_CREATED,
            {"state": run.state.value, "attempt_number": run.attempt_number},
            trace_id=run.trace_id,
            actor="run_store",
        )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.connect() as conn:
            self._ensure_wave0_columns(conn)
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
        transition_reason: str | None = None,
        cancellation_cause: str | None = None,
        retryable: bool | None = None,
        recovery_metadata_update: dict[str, Any] | None = None,
        attempt_number: int | None = None,
    ) -> RunRecord:
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run_id: {run_id}")
        validate_transition(run.state, target)
        now = utc_now()
        metadata = dict(run.metadata)
        if metadata_update:
            metadata.update(metadata_update)
        recovery = dict(run.recovery_metadata)
        if recovery_metadata_update:
            recovery.update(recovery_metadata_update)

        next_intent = intent if intent is not None else run.intent
        next_complexity = complexity if complexity is not None else run.complexity
        next_model = selected_model if selected_model is not None else run.selected_model
        next_output = output if output is not None else run.output
        next_error = error if error is not None else run.error
        next_reason = transition_reason if transition_reason is not None else run.transition_reason
        next_cancel = (
            cancellation_cause if cancellation_cause is not None else run.cancellation_cause
        )
        if target == RunState.CANCELLED and next_cancel is None:
            next_cancel = transition_reason or "cancelled"
        next_retryable = retryable if retryable is not None else run.retryable
        if target == RunState.FAILED and next_retryable is None:
            next_retryable = True
        next_attempt = attempt_number if attempt_number is not None else run.attempt_number

        with self.connect() as conn:
            self._ensure_wave0_columns(conn)
            conn.execute(
                """
                UPDATE runs SET
                    state = ?, intent = ?, complexity = ?, selected_model = ?,
                    output = ?, error = ?, metadata_json = ?, updated_at = ?,
                    transition_reason = ?, cancellation_cause = ?, retryable = ?,
                    recovery_metadata_json = ?, attempt_number = ?
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
                    next_reason,
                    next_cancel,
                    None if next_retryable is None else int(next_retryable),
                    json.dumps(recovery),
                    next_attempt,
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
                "transition_reason": next_reason,
                "cancellation_cause": next_cancel,
                "retryable": next_retryable,
                "attempt_number": next_attempt,
            },
            trace_id=run.trace_id,
            actor="run_store",
        )
        updated = self.get_run(run_id)
        assert updated is not None
        return updated

    def append_event(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        trace_id: str | None = None,
        job_id: str | None = None,
        actor: str | None = None,
        causal_parent: str | None = None,
        artifact_refs: tuple[str, ...] | list[str] | None = None,
        evidence_refs: tuple[str, ...] | list[str] | None = None,
    ) -> EventRecord:
        run = self.get_run(run_id)
        resolved_trace = trace_id or (run.trace_id if run else None)
        event = EventRecord(
            event_id=str(uuid.uuid4()),
            run_id=run_id,
            event_type=event_type,
            created_at=utc_now(),
            payload=payload or {},
            trace_id=resolved_trace,
            job_id=job_id,
            actor=actor,
            causal_parent=causal_parent,
            schema_version=EVENT_ENVELOPE_SCHEMA_VERSION,
            artifact_refs=tuple(artifact_refs or ()),
            evidence_refs=tuple(evidence_refs or ()),
        )
        with self.connect() as conn:
            self._ensure_wave0_columns(conn)
            conn.execute(
                """
                INSERT INTO run_events(
                    event_id, run_id, event_type, payload_json, created_at,
                    trace_id, job_id, actor, causal_parent, schema_version,
                    artifact_refs_json, evidence_refs_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.event_type.value,
                    json.dumps(event.payload),
                    event.created_at,
                    event.trace_id,
                    event.job_id,
                    event.actor,
                    event.causal_parent,
                    event.schema_version,
                    json.dumps(list(event.artifact_refs)),
                    json.dumps(list(event.evidence_refs)),
                ),
            )
        return event

    def list_events(self, run_id: str) -> list[EventRecord]:
        with self.connect() as conn:
            self._ensure_wave0_columns(conn)
            rows = conn.execute(
                """
                SELECT *
                FROM run_events WHERE run_id = ? ORDER BY created_at ASC, event_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> EventRecord:
        keys = set(row.keys())
        return EventRecord(
            event_id=row["event_id"],
            run_id=row["run_id"],
            event_type=EventType(row["event_type"]),
            created_at=row["created_at"],
            payload=json.loads(row["payload_json"] or "{}"),
            trace_id=row["trace_id"] if "trace_id" in keys else None,
            job_id=row["job_id"] if "job_id" in keys else None,
            actor=row["actor"] if "actor" in keys else None,
            causal_parent=row["causal_parent"] if "causal_parent" in keys else None,
            schema_version=int(row["schema_version"])
            if "schema_version" in keys and row["schema_version"] is not None
            else EVENT_ENVELOPE_SCHEMA_VERSION,
            artifact_refs=tuple(
                json.loads(row["artifact_refs_json"] or "[]")
                if "artifact_refs_json" in keys
                else []
            ),
            evidence_refs=tuple(
                json.loads(row["evidence_refs_json"] or "[]")
                if "evidence_refs_json" in keys
                else []
            ),
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        keys = set(row.keys())
        retryable_raw = row["retryable"] if "retryable" in keys else None
        retryable: bool | None
        if retryable_raw is None:
            retryable = None
        else:
            retryable = bool(retryable_raw)
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
            trace_id=row["trace_id"] if "trace_id" in keys else None,
            attempt_number=int(row["attempt_number"])
            if "attempt_number" in keys and row["attempt_number"] is not None
            else 1,
            transition_reason=row["transition_reason"] if "transition_reason" in keys else None,
            cancellation_cause=row["cancellation_cause"] if "cancellation_cause" in keys else None,
            retryable=retryable,
            recovery_metadata=json.loads(
                row["recovery_metadata_json"] or "{}"
                if "recovery_metadata_json" in keys
                else "{}"
            ),
        )


# Re-export for callers that import InvalidRunTransition via store usage.
__all__ = ["InvalidRunTransition", "RunStore"]
