"""SQLite persistence for cognitive runs / events / beliefs / experiences.

Uses the central LEVIATHAN database — no parallel DB.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .belief_state import BeliefItem, BeliefState
from .experience import VerifiedExperience
from .types import BeliefCategory, BeliefStatus, CognitiveRunStatus, EpistemicType


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CognitionStore:
    def __init__(self, db_path: Path | str | None = None, conn: sqlite3.Connection | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self._conn = conn
        self._owns_conn = conn is None and db_path is not None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self.db_path is None:
            raise RuntimeError("CognitionStore has no database path")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None

    def create_run(
        self,
        *,
        run_id: str | None = None,
        task_id: str,
        status: CognitiveRunStatus = CognitiveRunStatus.CREATED,
        conversation_id: str | None = None,
        task_json: dict[str, Any] | None = None,
        mode: str | None = None,
        strategy: str | None = None,
        shadow: bool = False,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rid = run_id or str(uuid.uuid4())
        now = _now()
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO cognitive_runs(
                run_id, task_id, conversation_id, status, mode, strategy, shadow,
                task_json, plan_json, belief_json, working_memory_json, budgets_json,
                usage_json, result_json, error, trace_id, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', '{}', '{}', '{}', NULL, ?, ?, ?, ?)
            """,
            (
                rid,
                task_id,
                conversation_id,
                status.value,
                mode,
                strategy,
                1 if shadow else 0,
                json.dumps(task_json or {}),
                trace_id,
                json.dumps(metadata or {}),
                now,
                now,
            ),
        )
        conn.commit()
        return self.get_run(rid) or {"run_id": rid, "status": status.value}

    def update_run(
        self,
        run_id: str,
        *,
        status: CognitiveRunStatus | None = None,
        plan_json: dict[str, Any] | None = None,
        belief_json: dict[str, Any] | None = None,
        working_memory_json: dict[str, Any] | None = None,
        budgets_json: dict[str, Any] | None = None,
        usage_json: dict[str, Any] | None = None,
        result_json: dict[str, Any] | None = None,
        mode: str | None = None,
        strategy: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        row = self.get_run(run_id)
        if row is None:
            return None
        fields: list[str] = []
        values: list[Any] = []
        mapping = {
            "status": status.value if status else None,
            "plan_json": json.dumps(plan_json) if plan_json is not None else None,
            "belief_json": json.dumps(belief_json) if belief_json is not None else None,
            "working_memory_json": json.dumps(working_memory_json) if working_memory_json is not None else None,
            "budgets_json": json.dumps(budgets_json) if budgets_json is not None else None,
            "usage_json": json.dumps(usage_json) if usage_json is not None else None,
            "result_json": json.dumps(result_json) if result_json is not None else None,
            "mode": mode,
            "strategy": strategy,
            "error": error,
            "metadata_json": json.dumps(metadata) if metadata is not None else None,
        }
        for col, val in mapping.items():
            if val is not None:
                fields.append(f"{col} = ?")
                values.append(val)
        fields.append("updated_at = ?")
        values.append(_now())
        values.append(run_id)
        conn = self.connect()
        conn.execute(f"UPDATE cognitive_runs SET {', '.join(fields)} WHERE run_id = ?", values)
        conn.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        conn = self.connect()
        row = conn.execute("SELECT * FROM cognitive_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(self, *, limit: int = 50, conversation_id: str | None = None) -> list[dict[str, Any]]:
        conn = self.connect()
        if conversation_id:
            rows = conn.execute(
                "SELECT * FROM cognitive_runs WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cognitive_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def add_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        stage: str | None = None,
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        now = _now()
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO cognitive_events(event_id, run_id, event_type, stage, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, run_id, event_type, stage, json.dumps(payload or {}), now),
        )
        conn.commit()
        return {
            "event_id": event_id,
            "run_id": run_id,
            "event_type": event_type,
            "stage": stage,
            "payload": payload or {},
            "created_at": now,
        }

    def list_events(self, run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT * FROM cognitive_events WHERE run_id = ?
            ORDER BY created_at ASC LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "run_id": r["run_id"],
                "event_type": r["event_type"],
                "stage": r["stage"],
                "payload": json.loads(r["payload_json"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def save_beliefs(self, run_id: str, beliefs: BeliefState) -> None:
        conn = self.connect()
        conn.execute("DELETE FROM cognitive_beliefs WHERE run_id = ?", (run_id,))
        for item in beliefs.items.values():
            conn.execute(
                """
                INSERT INTO cognitive_beliefs(
                    belief_id, run_id, proposition, category, confidence, status,
                    source_type, support_json, contradiction_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.belief_id,
                    run_id,
                    item.proposition,
                    item.category.value,
                    item.confidence,
                    item.status.value,
                    item.source_type.value,
                    json.dumps(item.support_refs),
                    json.dumps(item.contradiction_refs),
                    json.dumps(item.metadata),
                    item.created_at,
                    item.updated_at,
                ),
            )
        conn.commit()
        self.update_run(run_id, belief_json=beliefs.public_dict())

    def load_beliefs(self, run_id: str) -> BeliefState:
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM cognitive_beliefs WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        state = BeliefState()
        for r in rows:
            item = BeliefItem(
                belief_id=r["belief_id"],
                proposition=r["proposition"],
                category=BeliefCategory(r["category"]),
                confidence=float(r["confidence"]),
                support_refs=json.loads(r["support_json"] or "[]"),
                contradiction_refs=json.loads(r["contradiction_json"] or "[]"),
                source_type=EpistemicType(r["source_type"]),
                status=BeliefStatus(r["status"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                metadata=json.loads(r["metadata_json"] or "{}"),
            )
            state.items[item.belief_id] = item
        return state

    def save_experience(self, experience: VerifiedExperience) -> None:
        conn = self.connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO verified_experiences(
                experience_id, task_type, domain, task_summary, strategy, outcome,
                verification_status, admitted, admission_reason, privacy_class,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experience.experience_id,
                experience.task_type,
                experience.domain,
                experience.task_summary,
                experience.strategy,
                experience.outcome,
                experience.verification_status,
                1 if experience.admitted else 0,
                experience.admission_reason,
                experience.privacy_class,
                json.dumps(experience.public_dict()),
                experience.created_at,
            ),
        )
        conn.commit()

    def list_experiences(self, *, admitted_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        conn = self.connect()
        if admitted_only:
            rows = conn.execute(
                "SELECT payload_json FROM verified_experiences WHERE admitted = 1 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload_json FROM verified_experiences ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["payload_json"] or "{}") for r in rows]

    def reconcile_interrupted(self) -> list[str]:
        """Reconcile non-terminal runs after process restart.

        Durable wait states (WAITING_WORKER / WAITING_APPROVAL) stay resumable —
        they are backed by jobs/approvals outside this process. Active in-process
        stages are marked interrupted but remain resumable (not blindly FAILED)
        when a pending advance job exists or the run can be re-entered.
        """
        conn = self.connect()
        terminal = (
            "COMPLETED_VERIFIED",
            "COMPLETED_UNVERIFIED",
            "PARTIAL",
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "RESOURCE_EXHAUSTED",
            "BLOCKED",
            "SHADOW",
        )
        durable_wait = (
            CognitiveRunStatus.WAITING_WORKER.value,
            CognitiveRunStatus.WAITING_APPROVAL.value,
        )
        placeholders = ",".join("?" for _ in terminal)
        rows = conn.execute(
            f"SELECT run_id, status FROM cognitive_runs WHERE status NOT IN ({placeholders})",
            terminal,
        ).fetchall()
        updated: list[str] = []
        now = _now()
        for row in rows:
            run_id = row["run_id"]
            prior = row["status"]
            full = self.get_run(run_id) or {}
            meta = dict(full.get("metadata") or {})
            result = dict(full.get("result") or {})
            checkpoint = dict(result.get("checkpoint") or {})
            pending_job = (
                checkpoint.get("pending_advance_job_id")
                or result.get("pending_advance_job_id")
            )
            meta["reconciled"] = True
            meta["prior_status"] = prior
            meta["reconcile_at"] = now

            if prior in durable_wait or pending_job:
                # Keep durable wait / pending worker runs — restart-safe.
                new_status = (
                    prior
                    if prior in durable_wait
                    else CognitiveRunStatus.WAITING_WORKER.value
                )
                meta["reconcile_note"] = (
                    "process restart — durable wait preserved for resume"
                )
                meta["resumable"] = True
                meta["restart_safe"] = True
                conn.execute(
                    """
                    UPDATE cognitive_runs
                    SET status = ?, metadata_json = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (new_status, json.dumps(meta), now, run_id),
                )
            else:
                # In-process mid-flight without durable worker binding:
                # park as REASONING + resumable so resume()/hydrate() can continue.
                meta["reconcile_note"] = (
                    "process restart — in-process stage interrupted; resumable"
                )
                meta["resumable"] = True
                meta["interrupted_by_restart"] = True
                conn.execute(
                    """
                    UPDATE cognitive_runs
                    SET status = ?, error = ?, metadata_json = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        CognitiveRunStatus.REASONING.value,
                        "interrupted_by_restart",
                        json.dumps(meta),
                        now,
                        run_id,
                    ),
                )
            updated.append(run_id)
        conn.commit()
        return updated

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
        def _json(col: str) -> Any:
            raw = row[col]
            if raw is None or raw == "":
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}

        return {
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "conversation_id": row["conversation_id"],
            "status": row["status"],
            "mode": row["mode"],
            "strategy": row["strategy"],
            "shadow": bool(row["shadow"]),
            "task": _json("task_json"),
            "plan": _json("plan_json"),
            "beliefs": _json("belief_json"),
            "working_memory": _json("working_memory_json"),
            "budgets": _json("budgets_json"),
            "usage": _json("usage_json"),
            "result": _json("result_json"),
            "error": row["error"],
            "trace_id": row["trace_id"],
            "metadata": _json("metadata_json"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "truth": {
                "persisted_status_is_not_live_worker_proof": True,
                "no_private_cot_stored": True,
            },
        }
