"""CONTROL-owned ChatTurnStore — durable turn metadata references."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager

from Data.modules.common.sqlite_policy import open_sqlite_connection, ensure_wal

from .types import (
    ChatTurn,
    ChatTurnRunState,
    FailureClassification,
    InvalidTurnTransition,
    TERMINAL_TURN_STATES,
    validate_turn_transition,
    new_turn_id,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_COLUMNS = (
    "turn_id",
    "conversation_id",
    "user_message_id",
    "assistant_message_id",
    "chat_run_id",
    "cognition_run_id",
    "team_run_id",
    "operation_id",
    "activity_run_id",
    "requested_model",
    "effective_model",
    "requested_reasoning_mode",
    "effective_reasoning_mode",
    "collaboration_strategy",
    "behavior_profile_id",
    "behavior_version",
    "behavior_hash",
    "response_owner",
    "execution_path",
    "run_state",
    "streaming_effective",
    "streaming_degraded",
    "provisional",
    "cancelled",
    "failure_classification",
    "knowledge_hit_count",
    "memory_hit_count",
    "evidence_hit_count",
    "retrieval_coverage",
    "knowledge_available",
    "retrieval_requested",
    "verification_mode",
    "verification_state",
    "quality_state",
    "tool_receipt_ids_json",
    "decision_receipt_ids_json",
    "artifact_ids_json",
    "source_refs_json",
    "activity_ref",
    "detected_language",
    "requested_language",
    "response_language",
    "created_at",
    "started_at",
    "completed_at",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "context_used",
    "context_budget",
    "idempotency_key",
    "metadata_json",
    "error_summary",
)


class ChatTurnStore:
    """Persists ChatTurn rows in the CONTROL database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wal_ready = False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = open_sqlite_connection(self.path, set_wal=False)
        try:
            if not self._wal_ready:
                ensure_wal(conn)
                self._wal_ready = True
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

    def ensure_schema(self, conn: sqlite3.Connection | None = None) -> None:
        """Idempotent schema ensure (migrations also create the table)."""

        def _apply(c: sqlite3.Connection) -> None:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_turns (
                    turn_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_message_id INTEGER,
                    assistant_message_id INTEGER,
                    chat_run_id TEXT,
                    cognition_run_id TEXT,
                    team_run_id TEXT,
                    operation_id TEXT,
                    activity_run_id TEXT,
                    requested_model TEXT,
                    effective_model TEXT,
                    requested_reasoning_mode TEXT,
                    effective_reasoning_mode TEXT,
                    collaboration_strategy TEXT,
                    behavior_profile_id TEXT,
                    behavior_version TEXT,
                    behavior_hash TEXT,
                    response_owner TEXT NOT NULL DEFAULT 'unknown',
                    execution_path TEXT NOT NULL DEFAULT 'direct_chat',
                    run_state TEXT NOT NULL DEFAULT 'ACCEPTED',
                    streaming_effective INTEGER NOT NULL DEFAULT 0,
                    streaming_degraded INTEGER NOT NULL DEFAULT 0,
                    provisional INTEGER NOT NULL DEFAULT 0,
                    cancelled INTEGER NOT NULL DEFAULT 0,
                    failure_classification TEXT NOT NULL DEFAULT 'none',
                    knowledge_hit_count INTEGER,
                    memory_hit_count INTEGER,
                    evidence_hit_count INTEGER,
                    retrieval_coverage REAL,
                    knowledge_available INTEGER,
                    retrieval_requested INTEGER,
                    verification_mode TEXT,
                    verification_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    quality_state TEXT,
                    tool_receipt_ids_json TEXT NOT NULL DEFAULT '[]',
                    decision_receipt_ids_json TEXT NOT NULL DEFAULT '[]',
                    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_refs_json TEXT NOT NULL DEFAULT '[]',
                    activity_ref TEXT,
                    detected_language TEXT,
                    requested_language TEXT,
                    response_language TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    latency_ms REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    context_used INTEGER,
                    context_budget INTEGER,
                    idempotency_key TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    error_summary TEXT,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_turns_conversation "
                "ON chat_turns(conversation_id, created_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_turns_assistant_message "
                "ON chat_turns(assistant_message_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_turns_chat_run "
                "ON chat_turns(chat_run_id)"
            )
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_turns_idempotency "
                "ON chat_turns(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_turns_run_state "
                "ON chat_turns(run_state, created_at)"
            )

        if conn is not None:
            _apply(conn)
            return
        with self.connect() as c:
            _apply(c)

    def create_turn(
        self,
        *,
        conversation_id: str,
        user_message_id: int | None = None,
        chat_run_id: str | None = None,
        requested_model: str | None = None,
        requested_reasoning_mode: str | None = None,
        collaboration_strategy: str | None = None,
        idempotency_key: str | None = None,
        turn_id: str | None = None,
        **extra: Any,
    ) -> ChatTurn:
        if idempotency_key:
            existing = self.get_by_idempotency(idempotency_key)
            if existing is not None:
                return existing
        tid = turn_id or new_turn_id()
        now = _utc_now()
        filtered = {k: v for k, v in extra.items() if k in _COLUMNS and k not in {"turn_id", "conversation_id"}}
        turn = ChatTurn(
            turn_id=tid,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            chat_run_id=chat_run_id,
            activity_run_id=chat_run_id,
            requested_model=requested_model,
            requested_reasoning_mode=requested_reasoning_mode,
            collaboration_strategy=collaboration_strategy,
            run_state=filtered.pop("run_state", ChatTurnRunState.ACCEPTED.value),
            created_at=filtered.pop("created_at", now),
            started_at=filtered.pop("started_at", now),
            idempotency_key=idempotency_key,
            **filtered,
        )
        with self.connect() as conn:
            self.ensure_schema(conn)
            placeholders = ", ".join("?" for _ in _COLUMNS)
            cols = ", ".join(_COLUMNS)
            conn.execute(
                f"INSERT INTO chat_turns ({cols}) VALUES ({placeholders})",
                self._to_row(turn),
            )
        return turn

    def get(self, turn_id: str) -> ChatTurn | None:
        with self.connect() as conn:
            self.ensure_schema(conn)
            row = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM chat_turns WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_idempotency(self, key: str) -> ChatTurn | None:
        if not key:
            return None
        with self.connect() as conn:
            self.ensure_schema(conn)
            row = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM chat_turns WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_chat_run(self, chat_run_id: str) -> ChatTurn | None:
        with self.connect() as conn:
            self.ensure_schema(conn)
            row = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM chat_turns WHERE chat_run_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (chat_run_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_assistant_message(self, assistant_message_id: int) -> ChatTurn | None:
        with self.connect() as conn:
            self.ensure_schema(conn)
            row = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM chat_turns WHERE assistant_message_id = ?",
                (assistant_message_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
        before_created_at: str | None = None,
    ) -> list[ChatTurn]:
        with self.connect() as conn:
            self.ensure_schema(conn)
            if before_created_at:
                rows = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM chat_turns "
                    "WHERE conversation_id = ? AND created_at < ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (conversation_id, before_created_at, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM chat_turns "
                    "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                    (conversation_id, limit),
                ).fetchall()
        return [self._from_row(r) for r in rows]  # type: ignore[misc]

    def list_by_message_ids(self, message_ids: list[int]) -> dict[int, ChatTurn]:
        if not message_ids:
            return {}
        out: dict[int, ChatTurn] = {}
        with self.connect() as conn:
            self.ensure_schema(conn)
            # Chunk to stay under SQLite variable limits.
            for i in range(0, len(message_ids), 200):
                chunk = message_ids[i : i + 200]
                placeholders = ", ".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM chat_turns "
                    f"WHERE assistant_message_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    turn = self._from_row(row)
                    if turn and turn.assistant_message_id is not None:
                        out[int(turn.assistant_message_id)] = turn
        return out

    def transition(
        self,
        turn_id: str,
        target: ChatTurnRunState | str,
        **fields: Any,
    ) -> ChatTurn:
        turn = self.get(turn_id)
        if turn is None:
            raise KeyError(f"chat turn not found: {turn_id}")
        current = ChatTurnRunState(turn.run_state)
        next_state = ChatTurnRunState(target) if isinstance(target, str) else target
        validate_turn_transition(current, next_state)
        updates: dict[str, Any] = {"run_state": next_state.value}
        if next_state in TERMINAL_TURN_STATES and not fields.get("completed_at"):
            updates["completed_at"] = _utc_now()
        if next_state == ChatTurnRunState.CANCELLED:
            updates["cancelled"] = True
            if "failure_classification" not in fields:
                updates["failure_classification"] = FailureClassification.USER_CANCEL.value
        updates.update({k: v for k, v in fields.items() if k in _COLUMNS})
        return self.update(turn_id, **updates)

    def update(self, turn_id: str, **fields: Any) -> ChatTurn:
        allowed = {k: v for k, v in fields.items() if k in _COLUMNS and k != "turn_id"}
        if not allowed:
            existing = self.get(turn_id)
            if existing is None:
                raise KeyError(f"chat turn not found: {turn_id}")
            return existing
        sets = ", ".join(f"{k} = ?" for k in allowed)
        values = [self._encode_field(k, v) for k, v in allowed.items()]
        values.append(turn_id)
        with self.connect() as conn:
            self.ensure_schema(conn)
            conn.execute(f"UPDATE chat_turns SET {sets} WHERE turn_id = ?", values)
        updated = self.get(turn_id)
        if updated is None:
            raise KeyError(f"chat turn not found: {turn_id}")
        return updated

    def reconcile_stale_running(self, *, older_than_iso: str) -> list[ChatTurn]:
        """Mark ACCEPTED/RUNNING/STREAMING turns older than cutoff as INTERRUPTED."""
        interrupted: list[ChatTurn] = []
        with self.connect() as conn:
            self.ensure_schema(conn)
            rows = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM chat_turns "
                "WHERE run_state IN ('ACCEPTED', 'RUNNING', 'STREAMING') "
                "AND created_at < ?",
                (older_than_iso,),
            ).fetchall()
            for row in rows:
                turn = self._from_row(row)
                if turn is None:
                    continue
                try:
                    validate_turn_transition(
                        ChatTurnRunState(turn.run_state), ChatTurnRunState.INTERRUPTED
                    )
                except InvalidTurnTransition:
                    continue
                conn.execute(
                    "UPDATE chat_turns SET run_state = ?, failure_classification = ?, "
                    "completed_at = ?, error_summary = ? WHERE turn_id = ?",
                    (
                        ChatTurnRunState.INTERRUPTED.value,
                        FailureClassification.INTERRUPTED.value,
                        _utc_now(),
                        "reconciled after process restart",
                        turn.turn_id,
                    ),
                )
                turn.run_state = ChatTurnRunState.INTERRUPTED.value
                turn.failure_classification = FailureClassification.INTERRUPTED.value
                interrupted.append(turn)
        return interrupted

    def _to_row(self, turn: ChatTurn) -> tuple[Any, ...]:
        return tuple(self._encode_field(c, getattr(turn, c)) for c in _COLUMNS)

    def _encode_field(self, key: str, value: Any) -> Any:
        if key in {
            "streaming_effective",
            "streaming_degraded",
            "provisional",
            "cancelled",
            "knowledge_available",
            "retrieval_requested",
        }:
            if value is None:
                return None
            return 1 if value else 0
        if key.endswith("_json") and not isinstance(value, str):
            return json.dumps(value if value is not None else ([] if "ids" in key or "refs" in key else {}))
        return value

    def _from_row(self, row: sqlite3.Row | None) -> ChatTurn | None:
        if row is None:
            return None
        data = dict(row)
        for bool_key in (
            "streaming_effective",
            "streaming_degraded",
            "provisional",
            "cancelled",
        ):
            if bool_key in data:
                data[bool_key] = bool(data[bool_key])
        for opt_bool in ("knowledge_available", "retrieval_requested"):
            if opt_bool in data and data[opt_bool] is not None:
                data[opt_bool] = bool(data[opt_bool])
        return ChatTurn(**{k: data.get(k) for k in _COLUMNS})
