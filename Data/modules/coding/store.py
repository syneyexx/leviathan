"""SQLite persistence for coding sessions, turns, steps, and patches."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    CodingPatch,
    CodingSession,
    CodingStep,
    CodingTurn,
    DEFAULT_FEATURE_TRUTH,
    Mission,
    SessionStatus,
    StepKind,
    StepStatus,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class CodingStore:
    """Durable coding control-plane store (migration v15 tables)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
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
        # Mirror migration v15 so unit tests can use an isolated DB.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS coding_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                mission TEXT NOT NULL,
                status TEXT NOT NULL,
                workspace_root TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                user_goal TEXT NOT NULL DEFAULT '',
                conversation_id TEXT,
                run_id TEXT,
                model_id TEXT,
                error TEXT,
                verification_id TEXT,
                feature_truth_json TEXT NOT NULL DEFAULT '{}',
                neuro_json TEXT NOT NULL DEFAULT '{}',
                pending_capability_json TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                worker_pid INTEGER,
                round_count INTEGER NOT NULL DEFAULT 0,
                read_paths_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_coding_sessions_status
                ON coding_sessions(status, updated_at);
            CREATE TABLE IF NOT EXISTS coding_turns (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                content_raw TEXT,
                created_at TEXT NOT NULL,
                neuro_assessment_json TEXT,
                token_estimate INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_coding_turns_session
                ON coding_turns(session_id, seq);
            CREATE TABLE IF NOT EXISTS coding_steps (
                step_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT,
                seq INTEGER NOT NULL,
                kind TEXT NOT NULL,
                capability_id TEXT,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                approval_id TEXT,
                status TEXT NOT NULL,
                observation_id TEXT,
                effect_id TEXT,
                artifact_id TEXT,
                output_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                requested_by TEXT NOT NULL DEFAULT 'agent:coding',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_coding_steps_session
                ON coding_steps(session_id, seq);
            CREATE TABLE IF NOT EXISTS coding_patches (
                patch_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                artifact_id TEXT,
                path TEXT NOT NULL,
                diff_unified TEXT NOT NULL,
                hash_before TEXT,
                hash_after TEXT,
                applied INTEGER NOT NULL DEFAULT 0,
                approval_id TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_coding_patches_session
                ON coding_patches(session_id, created_at);
            """
        )

    # --- sessions -----------------------------------------------------------

    def create_session(
        self,
        *,
        mission: Mission,
        workspace_root: str,
        title: str = "",
        user_goal: str = "",
        conversation_id: str | None = None,
        model_id: str | None = None,
        status: SessionStatus = SessionStatus.CREATED,
        feature_truth: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodingSession:
        now = utc_now()
        session = CodingSession(
            session_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            mission=mission,
            status=status,
            workspace_root=workspace_root,
            title=title or (user_goal[:80] if user_goal else "Coding session"),
            user_goal=user_goal,
            conversation_id=conversation_id,
            model_id=model_id,
            feature_truth=dict(feature_truth or DEFAULT_FEATURE_TRUTH),
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_sessions (
                    session_id, created_at, updated_at, mission, status, workspace_root,
                    title, user_goal, conversation_id, run_id, model_id, error,
                    verification_id, feature_truth_json, neuro_json, pending_capability_json,
                    cancel_requested, worker_pid, round_count, read_paths_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.created_at,
                    session.updated_at,
                    session.mission.value,
                    session.status.value,
                    session.workspace_root,
                    session.title,
                    session.user_goal,
                    session.conversation_id,
                    session.run_id,
                    session.model_id,
                    session.error,
                    session.verification_id,
                    _json_dumps(session.feature_truth),
                    _json_dumps(session.neuro),
                    None,
                    0,
                    None,
                    0,
                    _json_dumps(session.read_paths),
                    _json_dumps(session.metadata),
                ),
            )
        return session

    def get_session(self, session_id: str) -> CodingSession | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM coding_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_session(row) if row else None

    def list_sessions(self, *, limit: int = 100) -> list[CodingSession]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM coding_sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_session(row) for row in rows]

    def update_session(self, session_id: str, **fields: Any) -> CodingSession:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        mapping = {
            "status": ("status", lambda v: v.value if isinstance(v, SessionStatus) else v),
            "mission": ("mission", lambda v: v.value if isinstance(v, Mission) else v),
            "title": ("title", str),
            "user_goal": ("user_goal", str),
            "conversation_id": ("conversation_id", lambda v: v),
            "run_id": ("run_id", lambda v: v),
            "model_id": ("model_id", lambda v: v),
            "error": ("error", lambda v: v),
            "verification_id": ("verification_id", lambda v: v),
            "feature_truth": ("feature_truth_json", _json_dumps),
            "neuro": ("neuro_json", _json_dumps),
            "pending_capability": ("pending_capability_json", lambda v: _json_dumps(v) if v is not None else None),
            "cancel_requested": ("cancel_requested", lambda v: 1 if v else 0),
            "worker_pid": ("worker_pid", lambda v: v),
            "round_count": ("round_count", int),
            "read_paths": ("read_paths_json", _json_dumps),
            "metadata": ("metadata_json", _json_dumps),
            "workspace_root": ("workspace_root", str),
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in mapping:
                continue
            column, caster = mapping[key]
            assignments.append(f"{column} = ?")
            values.append(caster(value))
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(session_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE coding_sessions SET {', '.join(assignments)} WHERE session_id = ?",
                values,
            )
        updated = self.get_session(session_id)
        assert updated is not None
        return updated

    def find_running_for_workspace(self, workspace_root: str) -> CodingSession | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM coding_sessions
                WHERE workspace_root = ? AND status IN ('RUNNING', 'WAITING_APPROVAL')
                ORDER BY updated_at DESC LIMIT 1
                """,
                (workspace_root,),
            ).fetchone()
        return self._row_session(row) if row else None

    def claim_next_runnable(self) -> CodingSession | None:
        """Claim one RUNNING session for the worker (sets worker_pid)."""
        import os

        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM coding_sessions
                WHERE status = 'RUNNING' AND cancel_requested = 0
                ORDER BY updated_at ASC LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE coding_sessions SET worker_pid = ?, updated_at = ? WHERE session_id = ?",
                (os.getpid(), utc_now(), row["session_id"]),
            )
        return self.get_session(row["session_id"])

    def list_waiting_approval(self) -> list[CodingSession]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM coding_sessions WHERE status = 'WAITING_APPROVAL'"
            ).fetchall()
        return [self._row_session(row) for row in rows]

    # --- turns --------------------------------------------------------------

    def next_turn_seq(self, session_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM coding_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["m"]) + 1

    def add_turn(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        content_raw: str | None = None,
        neuro_assessment: dict[str, Any] | None = None,
        token_estimate: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodingTurn:
        turn = CodingTurn(
            turn_id=str(uuid.uuid4()),
            session_id=session_id,
            seq=self.next_turn_seq(session_id),
            role=role,
            content=content,
            content_raw=content_raw,
            created_at=utc_now(),
            neuro_assessment=neuro_assessment,
            token_estimate=token_estimate,
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_turns (
                    turn_id, session_id, seq, role, content, content_raw,
                    created_at, neuro_assessment_json, token_estimate, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.turn_id,
                    turn.session_id,
                    turn.seq,
                    turn.role,
                    turn.content,
                    turn.content_raw,
                    turn.created_at,
                    _json_dumps(neuro_assessment) if neuro_assessment is not None else None,
                    turn.token_estimate,
                    _json_dumps(turn.metadata),
                ),
            )
            conn.execute(
                "UPDATE coding_sessions SET updated_at = ? WHERE session_id = ?",
                (utc_now(), session_id),
            )
        return turn

    def list_turns(self, session_id: str, *, limit: int = 500) -> list[CodingTurn]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coding_turns WHERE session_id = ?
                ORDER BY seq ASC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._row_turn(row) for row in rows]

    # --- steps --------------------------------------------------------------

    def next_step_seq(self, session_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM coding_steps WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["m"]) + 1

    def add_step(
        self,
        session_id: str,
        *,
        kind: StepKind,
        status: StepStatus = StepStatus.PENDING,
        turn_id: str | None = None,
        capability_id: str | None = None,
        arguments: dict[str, Any] | None = None,
        approval_id: str | None = None,
        observation_id: str | None = None,
        effect_id: str | None = None,
        artifact_id: str | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        requested_by: str = "agent:coding",
    ) -> CodingStep:
        now = utc_now()
        step = CodingStep(
            step_id=str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            seq=self.next_step_seq(session_id),
            kind=kind,
            status=status,
            capability_id=capability_id,
            arguments=dict(arguments or {}),
            approval_id=approval_id,
            observation_id=observation_id,
            effect_id=effect_id,
            artifact_id=artifact_id,
            output=dict(output or {}),
            error=error,
            requested_by=requested_by,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_steps (
                    step_id, session_id, turn_id, seq, kind, capability_id,
                    arguments_json, approval_id, status, observation_id, effect_id,
                    artifact_id, output_json, error, requested_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.step_id,
                    step.session_id,
                    step.turn_id,
                    step.seq,
                    step.kind.value,
                    step.capability_id,
                    _json_dumps(step.arguments),
                    step.approval_id,
                    step.status.value,
                    step.observation_id,
                    step.effect_id,
                    step.artifact_id,
                    _json_dumps(step.output),
                    step.error,
                    step.requested_by,
                    step.created_at,
                    step.updated_at,
                ),
            )
        return step

    def update_step(self, step_id: str, **fields: Any) -> CodingStep:
        step = self.get_step(step_id)
        if step is None:
            raise KeyError(f"Unknown step: {step_id}")
        mapping = {
            "status": ("status", lambda v: v.value if isinstance(v, StepStatus) else v),
            "approval_id": ("approval_id", lambda v: v),
            "observation_id": ("observation_id", lambda v: v),
            "effect_id": ("effect_id", lambda v: v),
            "artifact_id": ("artifact_id", lambda v: v),
            "output": ("output_json", _json_dumps),
            "error": ("error", lambda v: v),
            "arguments": ("arguments_json", _json_dumps),
            "capability_id": ("capability_id", lambda v: v),
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in mapping:
                continue
            column, caster = mapping[key]
            assignments.append(f"{column} = ?")
            values.append(caster(value))
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(step_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE coding_steps SET {', '.join(assignments)} WHERE step_id = ?",
                values,
            )
        updated = self.get_step(step_id)
        assert updated is not None
        return updated

    def get_step(self, step_id: str) -> CodingStep | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM coding_steps WHERE step_id = ?",
                (step_id,),
            ).fetchone()
        return self._row_step(row) if row else None

    def list_steps(self, session_id: str, *, limit: int = 500) -> list[CodingStep]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coding_steps WHERE session_id = ?
                ORDER BY seq ASC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._row_step(row) for row in rows]

    def get_pending_approval_step(self, session_id: str) -> CodingStep | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM coding_steps
                WHERE session_id = ? AND status = 'PENDING' AND kind IN ('CAPABILITY', 'WAIT_APPROVAL')
                ORDER BY seq DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._row_step(row) if row else None

    # --- patches ------------------------------------------------------------

    def add_patch(
        self,
        session_id: str,
        *,
        path: str,
        diff_unified: str,
        hash_before: str | None = None,
        hash_after: str | None = None,
        applied: bool = False,
        approval_id: str | None = None,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CodingPatch:
        patch = CodingPatch(
            patch_id=str(uuid.uuid4()),
            session_id=session_id,
            path=path,
            diff_unified=diff_unified,
            created_at=utc_now(),
            hash_before=hash_before,
            hash_after=hash_after,
            applied=applied,
            approval_id=approval_id,
            artifact_id=artifact_id,
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_patches (
                    patch_id, session_id, artifact_id, path, diff_unified,
                    hash_before, hash_after, applied, approval_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patch.patch_id,
                    patch.session_id,
                    patch.artifact_id,
                    patch.path,
                    patch.diff_unified,
                    patch.hash_before,
                    patch.hash_after,
                    1 if patch.applied else 0,
                    patch.approval_id,
                    patch.created_at,
                    _json_dumps(patch.metadata),
                ),
            )
        return patch

    def list_patches(self, session_id: str, *, limit: int = 200) -> list[CodingPatch]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coding_patches WHERE session_id = ?
                ORDER BY created_at ASC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._row_patch(row) for row in rows]

    # --- row mappers --------------------------------------------------------

    def _row_session(self, row: sqlite3.Row) -> CodingSession:
        pending_raw = row["pending_capability_json"]
        return CodingSession(
            session_id=row["session_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            mission=Mission(row["mission"]),
            status=SessionStatus(row["status"]),
            workspace_root=row["workspace_root"],
            title=row["title"] or "",
            user_goal=row["user_goal"] or "",
            conversation_id=row["conversation_id"],
            run_id=row["run_id"],
            model_id=row["model_id"],
            error=row["error"],
            verification_id=row["verification_id"],
            feature_truth=_json_loads(row["feature_truth_json"], dict(DEFAULT_FEATURE_TRUTH)),
            neuro=_json_loads(row["neuro_json"], {}),
            pending_capability=_json_loads(pending_raw, None) if pending_raw else None,
            cancel_requested=bool(row["cancel_requested"]),
            worker_pid=row["worker_pid"],
            round_count=int(row["round_count"] or 0),
            read_paths=list(_json_loads(row["read_paths_json"], [])),
            metadata=_json_loads(row["metadata_json"], {}),
        )

    def _row_turn(self, row: sqlite3.Row) -> CodingTurn:
        neuro_raw = row["neuro_assessment_json"]
        return CodingTurn(
            turn_id=row["turn_id"],
            session_id=row["session_id"],
            seq=int(row["seq"]),
            role=row["role"],
            content=row["content"] or "",
            content_raw=row["content_raw"],
            created_at=row["created_at"],
            neuro_assessment=_json_loads(neuro_raw, None) if neuro_raw else None,
            token_estimate=row["token_estimate"],
            metadata=_json_loads(row["metadata_json"], {}),
        )

    def _row_step(self, row: sqlite3.Row) -> CodingStep:
        return CodingStep(
            step_id=row["step_id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            seq=int(row["seq"]),
            kind=StepKind(row["kind"]),
            status=StepStatus(row["status"]),
            capability_id=row["capability_id"],
            arguments=_json_loads(row["arguments_json"], {}),
            approval_id=row["approval_id"],
            observation_id=row["observation_id"],
            effect_id=row["effect_id"],
            artifact_id=row["artifact_id"],
            output=_json_loads(row["output_json"], {}),
            error=row["error"],
            requested_by=row["requested_by"] or "agent:coding",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_patch(self, row: sqlite3.Row) -> CodingPatch:
        return CodingPatch(
            patch_id=row["patch_id"],
            session_id=row["session_id"],
            artifact_id=row["artifact_id"],
            path=row["path"],
            diff_unified=row["diff_unified"],
            hash_before=row["hash_before"],
            hash_after=row["hash_after"],
            applied=bool(row["applied"]),
            approval_id=row["approval_id"],
            created_at=row["created_at"],
            metadata=_json_loads(row["metadata_json"], {}),
        )
